import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('probe', Path(__file__).parents[1] / 'tools/probe_fan_policy.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

def buffer_output(data):
    lines = [f'[Buffer] Length {len(data):02X} =']
    for i in range(0, len(data), 16):
        lines.append(f'    {i:04X}: ' + ' '.join(f'{b:02X}' for b in data[i:i+16]) + ' // ................')
    return '\n'.join(lines) + '\n- '

class ProbeTests(unittest.TestCase):
    def test_zero_error_code_is_not_support(self):
        result = probe.parse_response(buffer_output(bytes(80)), 0)
        self.assertEqual(result['status'], 'empty_response')
        self.assertFalse(result['control_supported'])

    def test_nonempty_response_still_requires_validation(self):
        data = bytes(4) + bytes([6, 0]) + 'PWM'.encode('utf-16le') + bytes(68)
        result = probe.parse_response(buffer_output(data), 1)
        self.assertEqual(result['status'], 'unverified_response')
        self.assertEqual(bytes.fromhex(result['raw_hex']), data)
        self.assertFalse(result['control_supported'])

    def test_missing_buffer_bytes_fail(self):
        with self.assertRaises(ValueError):
            probe.parse_response('[Buffer] Length 50 =\n- ', 0)

    def test_acpi_failure_is_not_an_empty_response(self):
        with self.assertRaises(ValueError):
            probe.parse_response('Evaluation failed: AE_NOT_FOUND\n- ', 0)

    def test_parameter_table_parsing(self):
        self.assertEqual(probe.parameter_value('Description\n--\ndebug_layer = 0x00000200 ( * = enabled)', 'debug_layer'), 0x200)
        with self.assertRaises(ValueError):
            probe.parameter_value('unexpected format', 'debug_layer')

if __name__ == '__main__':
    unittest.main()
