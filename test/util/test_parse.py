# pylint: disable=missing-module-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-function-docstring
import unittest

import util.parse as parse


class TestParse(unittest.TestCase):
    def test_non_empty_dict_none_name(self):
        with self.assertRaises(ValueError):
            parse.non_empty_dict(None, {"test": True})  # type: ignore

    def test_non_empty_dict_empty_name(self):
        with self.assertRaises(ValueError):
            parse.non_empty_dict("", {"test": True})

    def test_non_empty_dict_none_value(self):
        with self.assertRaises(ValueError):
            parse.non_empty_dict("test", None)

    def test_non_empty_dict_list(self):
        with self.assertRaises(ValueError):
            parse.non_empty_dict("test", ["test"])

    def test_non_empty_dict_empty(self):
        with self.assertRaises(ValueError):
            parse.non_empty_dict("test", {})

    def test_non_empty_list_none_name(self):
        with self.assertRaises(ValueError):
            parse.non_empty_list(None, ["test"])  # type: ignore

    def test_non_empty_list_empty_name(self):
        with self.assertRaises(ValueError):
            parse.non_empty_dict("", ["test"])

    def test_non_empty_list_none_value(self):
        with self.assertRaises(ValueError):
            parse.non_empty_list("test", None)

    def test_non_empty_list_dict(self):
        with self.assertRaises(ValueError):
            parse.non_empty_list("test", {"test": True})

    def test_non_empty_list_empty(self):
        with self.assertRaises(ValueError):
            parse.non_empty_list("test", [])

    def test_non_empty_string_none_key(self):
        with self.assertRaises(ValueError):
            parse.non_empty_string(None, {"test": "value"}, "test")  # type: ignore

    def test_non_empty_string_empty_key(self):
        with self.assertRaises(ValueError):
            parse.non_empty_string("", {"test": "value"}, "test")

    def test_non_empty_string_none_dict_name(self):
        with self.assertRaises(ValueError):
            parse.non_empty_string("test", {"test": "value"}, None)  # type: ignore

    def test_non_empty_string_empty_dict_name(self):
        with self.assertRaises(ValueError):
            parse.non_empty_string("test", {"test": "value"}, "")

    def test_non_empty_string_none_dict(self):
        with self.assertRaises(ValueError):
            parse.non_empty_string("test", None, "test")

    def test_non_empty_string_empty_dict(self):
        with self.assertRaises(KeyError):
            parse.non_empty_string("test", {}, "test")

    def test_non_empty_string_no_key(self):
        with self.assertRaises(KeyError):
            parse.non_empty_string("missing", {"test": "value"}, "test")

    def test_non_empty_string_non_str_value(self):
        with self.assertRaises(KeyError):
            parse.non_empty_string("test", {"test": True}, "test")

    def test_non_empty_string_empty_value(self):
        with self.assertRaises(KeyError):
            parse.non_empty_string("test", {"test": ""}, "test")

    def test_non_empty_string_valid(self):
        self.assertEqual("value", parse.non_empty_string("test", {"test": "value"}, "test"))

    def test_default_string_none_key(self):
        with self.assertRaises(ValueError):
            parse.set_default_string(None, {"test": "value"}, "default")  # type: ignore

    def test_default_string_empty_key(self):
        with self.assertRaises(ValueError):
            parse.set_default_string("", {"test": "value"}, "default")

    def test_default_string_none_dict(self):
        with self.assertRaises(ValueError):
            parse.set_default_string("test", None, "default")  # type: ignore

    def test_default_string_empty_default(self):
        with self.assertRaises(ValueError):
            parse.set_default_string("test", {"test": "value"}, "")

    def test_default_string_none_default(self):
        with self.assertRaises(ValueError):
            parse.set_default_string("test", {"test": "value"}, None)  # type: ignore

    def test_default_string_empty_dict(self):
        cfg = {}
        parse.set_default_string("test", cfg, "default")
        self.assertEqual("default", cfg["test"])

    def test_default_string_empty_value(self):
        cfg = {"test": ""}
        parse.set_default_string("test", cfg, "default")
        self.assertEqual("default", cfg["test"])

    def test_default_string_none_value(self):
        cfg = {"test": None}
        parse.set_default_string("test", cfg, "default")
        self.assertEqual("default", cfg["test"])

    def test_str_list_empty_keys(self):
        with self.assertRaises(KeyError):
            parse.read_string_list_plurals(set(), {"key": ["test1, test2"]}, "value")

    def test_str_list_empty_key_value(self):
        with self.assertRaises(ValueError):
            parse.read_string_list_plurals({""}, {"key": ["test1, test2"]}, "value")

    def test_str_list_none_keys(self):
        with self.assertRaises(KeyError):
            parse.read_string_list_plurals(None, {"key": ["test1, test2"]}, "value")  # type: ignore

    def test_str_list_none_key_value(self):
        with self.assertRaises(ValueError):
            parse.read_string_list_plurals({None}, {"key": ["test1, test2"]}, "value")  # type: ignore

    def test_str_list_none_cfg(self):
        with self.assertRaises(ValueError):
            parse.read_string_list_plurals({"key"}, None, "value")

    def test_str_list_empty_value(self):
        with self.assertRaises(ValueError):
            parse.read_string_list_plurals({"key"}, {"key": ["test1, test2"]}, "")

    def test_str_list_none_value(self):
        with self.assertRaises(ValueError):
            parse.read_string_list_plurals({"key"}, {"key": ["test1, test2"]}, None)  # type: ignore

    def test_str_list_value_str(self):
        values = parse.read_string_list_plurals({"key"}, {"key": "test1"}, "value")
        self.assertIsNotNone(values)
        self.assertEqual(1, len(values))
        self.assertEqual("test1", values[0])

    def test_str_list_value_str_unique(self):
        values = parse.read_string_list_plurals({"key", "keys "}, {"key": "test1", "keys": "test1"}, "value")
        self.assertIsNotNone(values)
        self.assertEqual(1, len(values))
        self.assertEqual("test1", values[0])

    def test_str_list_value_empty(self):
        # empty string value ok, but do not return it
        values = parse.read_string_list_plurals({"key"}, {"key": ""}, "value")
        self.assertIsNotNone(values)
        self.assertEqual(0, len(values))

    def test_str_list_value_none(self):
        # error on unknown value type
        with self.assertRaises(KeyError):
            parse.read_string_list_plurals({"key"}, {"key": None}, "value")

    def test_str_list_list_value(self):
        values = parse.read_string_list_plurals({"key"}, {"key": ["test1", "test2"]}, "value")
        self.assertIsNotNone(values)
        self.assertEqual(2, len(values))
        self.assertIn("test1", values)
        self.assertIn("test2", values)

    def test_str_list_list_value_empty(self):
        values = parse.read_string_list_plurals({"key"}, {"key": ["test1", ""]}, "value")
        self.assertIsNotNone(values)
        self.assertEqual(1, len(values))
        self.assertIn("test1", values)

    def test_str_list_list_value_none(self):
        with self.assertRaises(ValueError):
            parse.read_string_list_plurals({"key"}, {"key": ["test1", None]}, "value")

    def test_str_list_list_value_duplicate(self):
        values = parse.read_string_list_plurals({"key", "keys"}, {"key": ["test1", ""], "keys": "test1"}, "value")
        self.assertIsNotNone(values)
        self.assertEqual(1, len(values))
        self.assertIn("test1", values)

    def test_cfg_def_empty_name(self):
        with self.assertRaises(ValueError):
            parse.configure_defaults("", {"key": "test"}, {"key": str}, {})

    def test_cfg_def_none_name(self):
        with self.assertRaises(ValueError):
            parse.configure_defaults(None, {"key": "test"}, {"key": str}, {})  # type: ignore

    def test_cfg_def_none_default(self):
        with self.assertRaises(ValueError):
            parse.configure_defaults("test", None, {"key": str}, {})  # type: ignore

    def test_cfg_def_none_types(self):
        with self.assertRaises(ValueError):
            parse.configure_defaults("test", {"key": "test"}, None, {})  # type: ignore

    def test_cfg_def_none_cfg(self):
        with self.assertRaises(ValueError):
            parse.configure_defaults("test", {"key": "test"}, {"key": str}, None)  # type: ignore

    def test_cfg_def_no_type(self):
        with self.assertRaises(KeyError):
            parse.configure_defaults("test", {"key": "test"}, {}, {})

    def test_cfg_def_invalid_type_def(self):
        with self.assertRaises(KeyError):
            parse.configure_defaults("test", {"key": []}, {"key": str}, {})

    def test_cfg_def_invalid_type_cfg(self):
        with self.assertRaises(KeyError):
            parse.configure_defaults("test", {"key": "test"}, {"key": str}, {"key": []})

    def test_cfg_def_use_default(self):
        cfg = {}
        parse.configure_defaults("test", {"key": "test"}, {"key": str}, cfg)
        self.assertIn("key", cfg)
        self.assertEqual("test", cfg["key"])

    def test_cfg_def_use_cfg(self):
        cfg = {"key": "cfg_test"}
        parse.configure_defaults("test", {"key": "test"}, {"key": str}, cfg)
        self.assertIn("key", cfg)
        self.assertEqual("cfg_test", cfg["key"])

    def test_cfg_def_allow_empty(self):
        cfg = {"key": ""}
        parse.configure_defaults("test", {"key": "test"}, {"key": str}, cfg)
        self.assertIn("key", cfg)
        self.assertEqual("", cfg["key"])
