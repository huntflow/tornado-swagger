# tests/helpers/test_pydantic_builders.py

import pytest
import tornado.web
from pydantic import BaseModel
from pydantic.dataclasses import dataclass

from tornado_swagger._builders import PydanticRoutesProcessor


class _DummySwaggerInfo:
    """Mimics tornado_swagger.setup.SwaggerMethodInfo for unit-tests."""
    def __init__(self, *, request=None, responses=None, query=None, tags=None):
        self.request = request
        # {status_code: {"model": <PydanticModel>, "description": Optional[str]}}
        self.responses = responses or {}
        self.query = query
        self.tags = tags


def _attach_swagger_info(callable_obj, **kwargs):
    # attach fake swagger metadata to handler method
    callable_obj._swagger_info = _DummySwaggerInfo(**kwargs)


class _SimpleBase(BaseModel):
    name: str
    age: int


@dataclass
class _SimpleDC:
    name: str
    age: int


def test_get_pydantic_schema_basemodel():
    schema = PydanticRoutesProcessor.get_pydantic_schema(_SimpleBase)
    assert schema["title"] == "_SimpleBase"
    assert schema["type"] == "object"
    assert "name" in schema["properties"]


def test_get_pydantic_schema_dataclass():
    schema = PydanticRoutesProcessor.get_pydantic_schema(_SimpleDC)
    assert schema["title"] == "_SimpleDC"
    assert schema["type"] == "object"
    assert "age" in schema["properties"]


def test_get_pydantic_schema_invalid_model():
    class _Invalid:
        pass

    with pytest.raises(TypeError):
        PydanticRoutesProcessor.get_pydantic_schema(_Invalid)


class _InputModel(BaseModel):
    query: str


class _OutputModel(BaseModel):
    result: str


@dataclass
class _InputDC:
    query: str


@dataclass
class _OutputDC:
    result: str


class _BaseHandler(tornado.web.RequestHandler):
    """Common parent to avoid linter warnings."""
    def initialize(self, *args, **kwargs):
        pass


class _BaseModelHandler(_BaseHandler):
    SUPPORTED_METHODS = ("POST",)

    def post(self):
        # never called in tests
        pass


class _DataclassHandler(_BaseHandler):
    SUPPORTED_METHODS = ("POST",)

    def post(self):
        # never called in tests
        pass


_attach_swagger_info(
    _BaseModelHandler.post,
    request=_InputModel,
    responses={200: {"model": _OutputModel}},
    tags=["BaseModel"],
)

_attach_swagger_info(
    _DataclassHandler.post,
    request=_InputDC,
    responses={200: {"model": _OutputDC}},
    tags=["Dataclass"],
)


@pytest.mark.parametrize(
    "handler_cls, route_regex, req_title, resp_title",
    [
        (_BaseModelHandler, r"/api/basemodel", "_InputModel", "_OutputModel"),
        (_DataclassHandler, r"/api/dataclass", "_InputDC", "_OutputDC"),
    ],
)
@pytest.mark.parametrize("route_kind", ["urlspec", "tuple"])
def test_extract_paths_pydantic(handler_cls, route_regex, req_title, resp_title, route_kind):
    if route_kind == "urlspec":
        route = tornado.web.url(route_regex, handler_cls)
    else:
        # Old-style tuple form should also be supported by builder.
        route = (route_regex, handler_cls)

    routes = [route]
    processor = PydanticRoutesProcessor()

    paths, components = processor.extract_paths_pydantic(routes)

    # exactly one path with POST operation
    assert len(paths) == 1
    path_item = next(iter(paths.values()))
    assert "post" in path_item
    post_spec = path_item["post"]

    # requestBody schema title matches the request model
    req_schema = post_spec["requestBody"]["content"]["application/json"]["schema"]
    assert req_schema["title"] == req_title

    # response schema is a $ref into components.schemas
    resp_spec = post_spec["responses"][200]
    resp_ref = resp_spec["content"]["application/json"]["schema"]["$ref"]
    ref_name = resp_ref.split("/")[-1]
    assert ref_name == resp_title
    assert ref_name in components["schemas"]
