import pytest
import tornado.web

from pydantic import BaseModel
from pydantic.dataclasses import dataclass

from tornado_swagger.const import API_OPENAPI_3_PYDANTIC
from tornado_swagger.setup import swagger_decorator
from tornado_swagger._builders import (
    PydanticRoutesProcessor,
    generate_doc_from_endpoints,
    DEFAULT_SUCCESS_DESCRIPTION,
    DEFAULT_FAIL_DESCRIPTION
)

SUCCESS_DESCRIPTION = "OK"
NOT_FOUND_DESCRIPTION = "Not found"
BASE_PATH = r"/api/items/(\d+)"
DOC_PATH = "/api/items/{item_id}"

class _ReqModel(BaseModel):
    name: str
    active: bool = True


class _QueryModel(BaseModel):
    limit: int
    offset: int = 0


@dataclass
class _RespDC:
    id: int
    name: str


class _DecoratedHandler(tornado.web.RequestHandler):
    SUPPORTED_METHODS = ("POST", "PUT")

    # заполнены все поля
    @swagger_decorator(
        request=_ReqModel,
        query=_QueryModel,
        description="Some test description",
        responses={
            200: {"model": _RespDC, "description": SUCCESS_DESCRIPTION},
            404: {"description": NOT_FOUND_DESCRIPTION},
        },
        tags=["decorated"],
    )
    def post(self, item_id: int):
        pass


    # минимальное заполнение
    @swagger_decorator(
        responses={
            200: {},
            403: {}
        },
        tags=["decorated"],
    )
    def put(self, item_id: int):
        pass

# Пример распаршенного объекта
# defaultdict(<class 'dict'>,
#             {'/api/items/{item_id}': {'post': {'description': 'Some test '
#                                                               'description',
#                                                'parameters': [{'in': 'path',
#                                                                'name': 'item_id',
#                                                                'required': True,
#                                                                'schema': {'format': 'int32',
#                                                                           'type': 'integer'}},
#                                                               {'in': 'query',
#                                                                'name': 'limit',
#                                                                'required': True,
#                                                                'schema': {'title': 'Limit',
#                                                                           'type': 'integer'}},
#                                                               {'in': 'query',
#                                                                'name': 'offset',
#                                                                'required': False,
#                                                                'schema': {'default': 0,
#                                                                           'title': 'Offset',
#                                                                           'type': 'integer'}}],
#                                                'requestBody': {'content': {'application/json': {'schema': {'properties': {'active': {'default': True,
#                                                                                                                                      'title': 'Active',
#                                                                                                                                      'type': 'boolean'},
#                                                                                                                           'name': {'title': 'Name',
#                                                                                                                                    'type': 'string'}},
#                                                                                                            'required': ['name'],
#                                                                                                            'title': '_ReqModel',
#                                                                                                            'type': 'object'}}},
#                                                                'required': True},
#                                                'responses': {200: {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/_RespDC'}}},
#                                                                    'description': 'OK'},
#                                                              404: {'description': 'Not '
#                                                                                   'found'}},
#                                                'tags': ['decorated']},
#                                       'put': {'parameters': [{'in': 'path',
#                                                               'name': 'item_id',
#                                                               'required': True,
#                                                               'schema': {'format': 'int32',
#                                                                          'type': 'integer'}}],
#                                               'responses': {200: {'description': 'Successful '
#                                                                                  'Response'},
#                                                             403: {'description': 'Bad '
#                                                                                  'request'}},
#                                               'tags': ['decorated']}}})
# ****************************************************************************************************
# {'parameters': {},
#  'schemas': {'_RespDC': {'properties': {'id': {'title': 'Id',
#                                                'type': 'integer'},
#                                         'name': {'title': 'Name',
#                                                  'type': 'string'}},
#                          'required': ['id', 'name'],
#                          'title': '_RespDC',
#                          'type': 'object'}}}




def test_decorator_builds_paths_from_urlspec():
    route = tornado.web.url(BASE_PATH, _DecoratedHandler)

    routes = [route]
    paths, components = PydanticRoutesProcessor().extract_paths_pydantic(routes)

    # пути одинаковые т.к. аргументы пути совпадают, но методы разные
    assert len(paths) == 1
    assert  len(paths[DOC_PATH]) == 2

def test_decorator_builds_paths_from_tuples():
    route = (BASE_PATH, _DecoratedHandler)

    routes = [route]
    paths, components = PydanticRoutesProcessor().extract_paths_pydantic(routes)

    # пути одинаковые т.к. аргументы пути совпадают, но методы разные
    assert len(paths) == 1
    assert  len(paths[DOC_PATH]) == 2


def test_decorator_post():
    route = tornado.web.url(BASE_PATH, _DecoratedHandler)

    routes = [route]
    paths, components = PydanticRoutesProcessor().extract_paths_pydantic(routes)

    path = next((p for p in paths.keys()), None)
    assert path == DOC_PATH
    post_spec = next((params for params in paths.values()), {}).get("post")
    assert post_spec

    # Теги
    assert "tags" in post_spec and post_spec["tags"] == ["decorated"]

    # requestBody: схема инлайн, заголовок соответствует модели
    req_schema = post_spec["requestBody"]["content"]["application/json"]["schema"]
    assert req_schema["title"] == "_ReqModel"
    assert req_schema["type"] == "object"
    assert req_schema["required"] == ["name"]
    # Параметры схемы
    req_schema_properties = req_schema["properties"]
    assert "name" in req_schema["properties"]
    assert  req_schema_properties["name"]["type"] == "string"
    assert "active" in req_schema["properties"]
    assert  req_schema_properties["active"]["type"] == "boolean"
    assert  req_schema_properties["active"]["default"] == True

    # query-параметры из _QueryModel
    qparams = {p["name"]: p for p in post_spec.get("parameters", []) if p["in"] == "query"}
    assert "limit" in qparams and qparams["limit"]["schema"]["type"] == "integer"
    assert qparams["limit"]["required"] is True
    assert "offset" in qparams and qparams["offset"]["required"] is False
    assert "limit" in qparams and qparams["offset"]["schema"]["type"] == "integer"

    # path-параметр item_id (int)
    pparams = [p for p in post_spec.get("parameters", []) if p["in"] == "path"]
    assert any(p["name"] == "item_id" and p["schema"]["type"] in "integer" for p in pparams)

    #ответы
    resp_200 = post_spec["responses"][200]
    ref = resp_200["content"]["application/json"]["schema"]["$ref"]
    ref_name = ref.split("/")[-1]
    assert ref_name == "_RespDC"
    assert ref_name in components["schemas"]
    assert resp_200["description"] == SUCCESS_DESCRIPTION

    resp_404 = post_spec["responses"][404]
    assert resp_404["description"] == NOT_FOUND_DESCRIPTION

    # модель ответа (pydantic dataclass)
    response = components["schemas"]["_RespDC"]
    assert response["required"] == ["id", "name"]
    assert response["properties"]["id"]["type"] == "integer"
    assert response["properties"]["name"]["type"] == "string"


def test_decorator_put():
    # Декоратор с минимальным набором полей
    route = tornado.web.url(BASE_PATH, _DecoratedHandler)

    routes = [route]
    paths, components = PydanticRoutesProcessor().extract_paths_pydantic(routes)

    path = next((p for p in paths.keys()), None)
    assert path == DOC_PATH
    put_spec = next((params for params in paths.values()), {}).get("put")
    assert put_spec

    # Теги
    assert "tags" in put_spec and put_spec["tags"] == ["decorated"]

    # path-параметр item_id (int)
    pparams = [p for p in put_spec.get("parameters", []) if p["in"] == "path"]
    assert any(p["name"] == "item_id" and p["schema"]["type"] in "integer" for p in pparams)

    # Описания кодов ответа
    resp_200 = put_spec["responses"][200]
    assert resp_200["description"] == DEFAULT_SUCCESS_DESCRIPTION

    resp_403 = put_spec["responses"][403]
    assert resp_403["description"] == DEFAULT_FAIL_DESCRIPTION


def test_decorator_end_to_end_generate_doc_from_endpoints():
    routes = [tornado.web.url(BASE_PATH, _DecoratedHandler)]

    docs = generate_doc_from_endpoints(
        routes=routes,
        api_base_url="/",
        description="",
        api_version="1.0.0",
        title="Test API",
        contact="",
        schemes=["http"],
        security_definitions=None,
        security=None,
        api_definition_version=API_OPENAPI_3_PYDANTIC,
    )

    assert "openapi" in docs and docs["openapi"].startswith("3.")
    assert DOC_PATH in docs["paths"]

    post_spec = docs["paths"][DOC_PATH]["post"]
    # базовые поля операции
    assert "responses" in post_spec
    assert "requestBody" in post_spec
    assert "tags" in post_spec and post_spec["tags"] == ["decorated"]

    # components содержит схему ответа
    comp = docs["components"]["schemas"]
    assert "_RespDC" in comp and comp["_RespDC"]["type"] == "object"
