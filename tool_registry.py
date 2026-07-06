# Tool Registry...

import importlib
import json
from pathlib import Path

from dotenv import load_dotenv
from core.interrupts import OperationInterrupted

# Load config.env from ~/.lumakit/ first (user overrides), then repo-root .env
_user_env = Path.home() / ".lumakit" / "config.env"
if _user_env.exists():
    load_dotenv(_user_env)
load_dotenv()  # repo-root .env — won't override keys already set

class ToolRegistry:
    def __init__(self):
        self.tools = {}
        self.version = 0

    def register(self, tool, *, group=None, llm_exposed=None):
        tool = dict(tool)
        if group is not None:
            tool.setdefault("group", group)
        else:
            tool.setdefault("group", "general")
        if llm_exposed is not None:
            tool["llm_exposed"] = bool(llm_exposed)
        else:
            tool.setdefault("llm_exposed", True)
        self.tools[tool['name']] = tool
        self.version += 1

    def get(self, name):
        return self.tools.get(name)
    
    def list(self, *, groups=None, include_hidden=False):
        group_filter = set(groups or [])
        return [
            {
                'name': tool['name'],
                'description': tool ['description'],
                'group': tool.get('group', 'general'),
            }
            for tool in self.tools.values()
            if (include_hidden or tool.get("llm_exposed", True))
            and (not group_filter or tool.get("group") in group_filter)
        ]
    
    # Defined at module level (below the class) — inside the class body the
    # name `list` resolves to the ToolRegistry.list METHOD, not the builtin.
    _JSON_TYPE_MAP = None  # populated after the class definition

    @staticmethod
    def normalize_inputs(inputs):
        """Models sometimes pass the whole argument object as a JSON string —
        parse it back into a dict so every surface behaves identically."""
        if inputs is None:
            return {}
        if isinstance(inputs, str):
            try:
                parsed = json.loads(inputs)
            except json.JSONDecodeError:
                raise ValueError("Tool arguments must be a JSON object, got an unparseable string.")
            if not isinstance(parsed, dict):
                raise ValueError("Tool arguments must be a JSON object.")
            return parsed
        if not isinstance(inputs, dict):
            raise ValueError(f"Tool arguments must be a JSON object, got {type(inputs).__name__}.")
        return inputs

    def _coerce_value(self, value, expected):
        """Forgiving coercion for common model mistakes ('5' for 5, 'true' for
        true). Returns (coerced_value, ok)."""
        if expected == 'integer' and isinstance(value, str):
            try:
                return int(value.strip()), True
            except ValueError:
                return value, False
        if expected == 'number' and isinstance(value, str):
            try:
                return float(value.strip()), True
            except ValueError:
                return value, False
        if expected == 'boolean' and isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ('true', 'yes', '1'):
                return True, True
            if lowered in ('false', 'no', '0'):
                return False, True
            return value, False
        return value, False

    def validate_inputs(self, inputs, schema):
        """Validate (and lightly coerce) inputs against the declared JSON
        schema: required keys, types, enums, numeric bounds, array item types.
        Raises ValueError with a message the model can correct from. Returns
        the normalized inputs dict."""
        if not isinstance(schema, dict):
            return inputs

        for field in schema.get('required', []):
            if field not in inputs or inputs[field] is None:
                raise ValueError(f"Missing required input: {field}")

        properties = schema.get('properties')
        if not isinstance(properties, dict):
            return inputs

        for key, value in list(inputs.items()):
            spec = properties.get(key)
            if not isinstance(spec, dict) or value is None:
                continue

            expected = spec.get('type')
            if expected in self._JSON_TYPE_MAP:
                py_type = self._JSON_TYPE_MAP[expected]
                # bool is an int subclass — don't accept True for integer/number
                type_ok = isinstance(value, py_type) and not (
                    expected in ('integer', 'number') and isinstance(value, bool)
                )
                if not type_ok:
                    value, coerced = self._coerce_value(value, expected)
                    if coerced:
                        inputs[key] = value
                    else:
                        raise ValueError(
                            f"Invalid type for '{key}': expected {expected}, "
                            f"got {type(inputs[key]).__name__} ({str(inputs[key])[:80]!r})"
                        )

            enum = spec.get('enum')
            if isinstance(enum, list) and enum and value not in enum:
                allowed = ", ".join(repr(item) for item in enum[:10])
                raise ValueError(f"Invalid value for '{key}': must be one of {allowed}")

            if expected in ('integer', 'number'):
                minimum = spec.get('minimum')
                maximum = spec.get('maximum')
                if minimum is not None and inputs[key] < minimum:
                    raise ValueError(f"'{key}' must be >= {minimum}, got {inputs[key]}")
                if maximum is not None and inputs[key] > maximum:
                    raise ValueError(f"'{key}' must be <= {maximum}, got {inputs[key]}")

            if expected == 'array':
                item_spec = spec.get('items')
                item_type = item_spec.get('type') if isinstance(item_spec, dict) else None
                if item_type in self._JSON_TYPE_MAP:
                    item_py = self._JSON_TYPE_MAP[item_type]
                    for i, item in enumerate(inputs[key]):
                        if not isinstance(item, item_py):
                            raise ValueError(
                                f"Invalid item in '{key}[{i}]': expected {item_type}, "
                                f"got {type(item).__name__}"
                            )
        return inputs

    def execute(self, name, inputs=None):
        tool = self.get(name)
        if tool is None:
            return {'success': False, 'error': f"Tool not found: {name}"}

        try:
            inputs = self.normalize_inputs(inputs)
            inputs = self.validate_inputs(inputs, tool['inputSchema'])
            result = tool['execute'](inputs)
            # One error contract (D-8): tools may raise, return
            # {'success': False, ...}, or return a bare {'error': ...} dict —
            # all of them must surface as success=false, never as a
            # "successful" result whose payload happens to contain an error.
            if isinstance(result, dict) and (
                result.get('success') is False
                or (result.get('error') and 'success' not in result)
            ):
                return {
                    'success': False,
                    'error': str(result.get('error') or 'Tool reported failure'),
                    'toolName': name,
                    'data': result,
                }
            return {'success': True, 'data': result}
        except OperationInterrupted as e:
            return {
                'success': False,
                'error': str(e),
                'toolName': name,
                'interrupted': True,
            }
        except Exception as e:
            return {'success': False, 'error': str(e), 'toolName': name}    

    def load_tools_from_folder(self, folder_path='tools', skip_dirs=None):
        base_path = Path(folder_path)
        if not base_path.is_absolute():
            base_path = Path(__file__).resolve().parent / base_path
        skip_dirs = set(skip_dirs or [])

        if not base_path.exists():
            print(f"Tools folder not found: {folder_path}")
            return

        search_root = base_path.parent if base_path.parent != Path('') else Path('.')

        for module_path in sorted(base_path.rglob('*.py')):
            if module_path.name == '__init__.py':
                continue
            if module_path.parent == base_path and module_path.name.endswith('_tools.py'):
                continue
            if any(part in skip_dirs for part in module_path.parts):
                continue

            import_path = ".".join(module_path.with_suffix('').relative_to(search_root).parts)
            try:
                module = importlib.import_module(import_path)
            except ImportError as exc:
                # Optional stacks (playwright, pyautogui, pyperclip, ...) may
                # not be installed on a core install — skip those tools and
                # keep the rest of the agent working.
                from core import log
                log.warn("tools", f"skipping {import_path}: missing dependency", exc)
                continue

            for attr_name in dir(module):
                if attr_name.startswith('get_') and attr_name.endswith('_tool'):
                    tool_func = getattr(module, attr_name)
                    tool = tool_func()
                    self.register(tool, group=self._infer_group(module_path, base_path))

    def _infer_group(self, module_path: Path, base_path: Path) -> str:
        try:
            rel_parts = module_path.relative_to(base_path).parts
        except ValueError:
            return "general"
        if len(rel_parts) > 1:
            return rel_parts[0]
        return "general"


ToolRegistry._JSON_TYPE_MAP = {
    'string': str,
    'integer': int,
    'number': (int, float),
    'boolean': bool,
    'array': list,
    'object': dict,
}


