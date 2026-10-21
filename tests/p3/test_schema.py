import pytest

from agentguard.policies import PathRule
from agentguard.policies.schema import matches_schema, validate_schema

pytestmark = pytest.mark.p3


@pytest.mark.parametrize(
    ("schema", "good", "bad"),
    [
        ({"type": "integer", "minimum": 1, "maximum": 3}, 2, True),
        ({"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 2}, 1.5, 2),
        ({"type": "string", "minLength": 1, "maxLength": 3}, "ok", "long"),
        ({"type": "boolean", "enum": [True]}, True, 1),
        ({"type": "null"}, None, "null"),
        (
            {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 2},
            [1],
            [True],
        ),
        (
            {
                "type": "object",
                "properties": {"x": {"type": "integer"}},
                "required": ["x"],
                "additionalProperties": False,
                "maxProperties": 1,
            },
            {"x": 1},
            {"x": 1, "extra": 2},
        ),
    ],
)
def test_strict_schema_subset(schema, good, bad):
    validate_schema(schema)
    assert matches_schema(good, schema)
    assert not matches_schema(bad, schema)


@pytest.mark.parametrize(
    "schema",
    [
        {},
        {"type": "object"},
        {"type": "array"},
        {"type": "string", "pattern": "(x+)+$"},
        {"type": "object", "additionalProperties": True},
        {"type": "object", "properties": {}, "required": ["x"], "additionalProperties": False},
        {"type": "string", "maxLength": True},
        {"type": "number", "minimum": "1"},
        {"type": "number", "minimum": float("inf")},
        {"type": "string", "enum": []},
        {"type": "string", "format": "uri"},
        {"type": "string", "$ref": "file:///unused"},
    ],
)
def test_unsupported_or_malformed_schema_rejected_without_io(schema):
    with pytest.raises(ValueError):
        validate_schema(schema)


def test_schema_and_binding_configuration_are_detached(harness):
    original_digest = harness.tool.metadata_digest
    harness.schema["properties"]["path"]["type"] = "integer"
    public = harness.tool.parameters_schema
    public["properties"].clear()
    assert harness.tool.parameters_schema["properties"]["path"]["type"] == "string"
    assert harness.tool.metadata_digest == original_digest
    assert harness.executor().execute(harness.call(), harness.context()).executed


def test_duplicate_bindings_fail_configuration(harness):
    with pytest.raises(ValueError, match="Duplicate"):
        harness.executor(tools=[harness.tool, harness.tool])


def test_missing_permissions_cannot_create_unrestricted_binding(harness):
    with pytest.raises(ValueError, match="explicit permissions"):
        harness.binding(permissions=[])


def test_async_handlers_fail_configuration(harness):
    async def handler(path):
        return path

    with pytest.raises(ValueError, match="Invalid tool configuration"):
        harness.binding(handler=handler)


def test_nonexistent_write_leaf_stays_in_configured_resource(harness):
    def write(path):
        harness.count.append(path)
        with open(path, "x", encoding="utf-8") as output:
            output.write("public note")
        return "created"

    tool = harness.binding(
        handler=write, paths=(PathRule("path", "resource.public", harness.root, must_exist=False),)
    )
    result = harness.executor(tools=[tool]).execute(
        harness.call(selected=tool, arguments={"path": "note.txt"}), harness.context()
    )
    assert result.executed and result.value == "created"
    assert (harness.root / "note.txt").read_text() == "public note"
