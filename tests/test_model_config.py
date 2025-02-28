# Copyright (c) 2021, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest
import os
from .common import test_result_collector as trc
from .mocks.mock_model_config import MockModelConfig
from unittest.mock import mock_open, patch, MagicMock

from model_analyzer.triton.model.model_config import ModelConfig
from model_analyzer.model_analyzer_exceptions \
    import TritonModelAnalyzerException


class TestModelConfig(trc.TestResultCollector):

    def setUp(self):
        self._model_config = {
            'name': 'classification_chestxray_v1',
            'platform': 'tensorflow_graphdef',
            'max_batch_size': 32,
            'input': [{
                'name': 'NV_MODEL_INPUT',
                'data_type': 'TYPE_FP32',
                'format': 'FORMAT_NHWC',
                'dims': ['256', '256', '3']
            }],
            'output': [{
                'name': 'NV_MODEL_OUTPUT',
                'data_type': 'TYPE_FP32',
                'dims': ['15'],
                'label_filename': 'chestxray_labels.txt'
            }],
            'instance_group': [{
                'count': 1,
                'kind': 'KIND_GPU'
            }]
        }

        # Equivalent protobuf for the model config above.
        self._model_config_protobuf = """
name: "classification_chestxray_v1"
platform: "tensorflow_graphdef"
max_batch_size: 32
input [
  {
    name: "NV_MODEL_INPUT"
    data_type: TYPE_FP32
    format: FORMAT_NHWC
    dims: [256, 256, 3]
  }
]
output [
  {
    name: "NV_MODEL_OUTPUT"
    data_type: TYPE_FP32
    dims: [15]
    label_filename: "chestxray_labels.txt"
  }
]
instance_group [
  {
    kind: KIND_GPU
    count: 1
  }
]
"""

    def tearDown(self):
        patch.stopall()

    def test_create_from_file(self):
        test_protobuf = self._model_config_protobuf
        mock_model_config = MockModelConfig(test_protobuf)
        mock_model_config.start()
        model_config = ModelConfig._create_from_file('/path/to/model_config')
        self.assertTrue(model_config.get_config() == self._model_config)
        mock_model_config.stop()

    def test_create_from_dict(self):
        model_config = ModelConfig.create_from_dictionary(self._model_config)
        self.assertTrue(model_config.get_config() == self._model_config)

        new_config = {'instance_group': [{'count': 2, 'kind': 'KIND_CPU'}]}
        model_config.set_config(new_config)
        self.assertTrue(model_config.get_config() == new_config)

    def test_write_config_file(self):
        model_config = ModelConfig.create_from_dictionary(self._model_config)
        model_output_path = os.path.abspath('./model_config')

        mock_model_config = MockModelConfig()
        mock_model_config.start()
        # Write the model config to output
        with patch('model_analyzer.triton.model.model_config.open',
                   mock_open()) as mocked_file:
            with patch('model_analyzer.triton.model.model_config.copy_tree',
                       MagicMock()):
                model_config.write_config_to_file(model_output_path,
                                                  '/mock/path', None)
            content = mocked_file().write.call_args.args[0]
        mock_model_config.stop()

        mock_model_config = MockModelConfig(content)
        mock_model_config.start()
        model_config_from_file = \
            ModelConfig._create_from_file(model_output_path)
        self.assertTrue(
            model_config_from_file.get_config() == self._model_config)
        mock_model_config.stop()

        # output path doesn't exist
        with patch('model_analyzer.triton.model.model_config.os.path.exists',
                   MagicMock(return_value=False)):
            with self.assertRaises(TritonModelAnalyzerException):
                ModelConfig._create_from_file(model_output_path)

        # output path is a file
        with patch('model_analyzer.triton.model.model_config.os.path.isfile',
                   MagicMock(return_value=True)):
            with self.assertRaises(TritonModelAnalyzerException):
                ModelConfig._create_from_file(model_output_path)

    @patch('model_analyzer.triton.model.model_config.os.listdir',
           MagicMock(return_value=['1', 'config.pbtxt', 'output0_labels.txt']))
    @patch('model_analyzer.triton.model.model_config.copy_tree')
    @patch('model_analyzer.triton.model.model_config.os.symlink')
    def test_write_config_to_file_with_relative_path(self, mock_os_symlink,
                                                     *args):
        """
        Tests that the call to os.symlink() within write_config_to_file() uses
        a valid relative path when user uses a relative path with the
        `--output-model-repository-path` option
        """

        model_config = ModelConfig.create_from_dictionary(self._model_config)

        model_path = './output_model_repository/model_config_1'
        src_model_path = '/tmp/src_model_repository/model'
        last_model_path = './output_model_repository/model_config_0'

        mock_model_config = MockModelConfig()
        mock_model_config.start()
        model_config.write_config_to_file(model_path, src_model_path,
                                          last_model_path)
        mock_model_config.stop()

        mock_os_symlink.assert_any_call(
            '../model_config_0/1', './output_model_repository/model_config_1/1')
        mock_os_symlink.assert_any_call(
            '../model_config_0/output0_labels.txt',
            './output_model_repository/model_config_1/output0_labels.txt')

    def test_instance_group_string(self):
        """ Test out all corner cases of instance_group_string() """

        def _test_helper(config_dict, expected_result, gpu_count=None):
            model_config = ModelConfig.create_from_dictionary(config_dict)
            if gpu_count:
                instance_group_str = model_config.instance_group_string(
                    gpu_count)
            else:
                instance_group_str = model_config.instance_group_string()
            self.assertEqual(instance_group_str, expected_result)

        # No instance group info in model_config_dict:
        #  - default to 1 per GPU
        model_config_dict = {}
        _test_helper(model_config_dict, "1:GPU", gpu_count=1)

        # No instance group info in model_config_dict:
        #  - 1 per GPU -- if 2 gpus then 2 total
        model_config_dict = {}
        _test_helper(model_config_dict, "2:GPU", gpu_count=2)

        # No instance group info in model_config_dict:
        #  - default to 1 on CPU if cuda not available
        model_config_dict = {}
        with patch('numba.cuda.is_available', MagicMock(return_value=False)):
            _test_helper(model_config_dict, "1:CPU", gpu_count=5)

        # 2 per GPU, 3 gpus in the system = 6 total
        model_config_dict = {
            'instance_group': [{
                'count': 2,
                'kind': 'KIND_GPU',
            }]
        }
        _test_helper(model_config_dict, "6:GPU", gpu_count=3)

        # 1 on GPU0 only = 1 total despite 2 GPUs in the system
        model_config_dict = {
            'instance_group': [{
                'count': 1,
                'kind': 'KIND_GPU',
                'gpus': [0]
            }]
        }
        _test_helper(model_config_dict, "1:GPU", gpu_count=2)

        # 1 on ALL gpus + 2 each on [1 and 3] + 3 more on CPUs
        # with 4 GPUs in the system:
        #   8 on GPU and 3 on CPU
        model_config_dict = {
            'instance_group': [
                {
                    'count': 1,
                    'kind': 'KIND_GPU'
                },
                {
                    'count': 2,
                    'kind': 'KIND_GPU',
                    'gpus': [1, 3]
                },
                {
                    'count': 3,
                    'kind': 'KIND_CPU'
                },
            ]
        }
        _test_helper(model_config_dict, "8:GPU + 3:CPU", gpu_count=4)


if __name__ == '__main__':
    unittest.main()
