"""Setup"""
import os
import typing
from dataclasses import dataclass

import tornado.web
from pydantic import BaseModel

from tornado_swagger._builders import generate_doc_from_endpoints
from tornado_swagger._handlers import SwaggerSpecHandler, SwaggerUiHandler
from tornado_swagger.const import API_SWAGGER_2

STATIC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "swagger_ui"))


def export_swagger(
    routes: typing.List[tornado.web.URLSpec],
    *,
    api_base_url: str = "/",
    description: str = "Swagger API definition",
    api_version: str = "1.0.0",
    title: str = "Swagger API",
    contact: str = "",
    schemes: list = None,
    security_definitions: dict = None,
    security: list = None,
    api_definition_version: str = API_SWAGGER_2
):
    """Export swagger schema as dict"""
    return generate_doc_from_endpoints(
        routes,
        api_base_url=api_base_url,
        description=description,
        api_version=api_version,
        title=title,
        contact=contact,
        schemes=schemes,
        security_definitions=security_definitions,
        security=security,
        api_definition_version=api_definition_version,
    )


@dataclass
class SwaggerMethodInfo:
    responses: typing.Dict[int, typing.Dict[str, typing.Any]]
    request: typing.Optional[typing.Type[BaseModel]] = None
    query: typing.Optional[typing.Type[BaseModel]] = None
    tags: typing.Optional[typing.List[str]] = None


def swagger_decorator(
        *,
        responses: typing.Dict[int, typing.Dict[str, typing.Any]],
        request: typing.Optional[typing.Type[BaseModel]] = None,
        query: typing.Optional[typing.Type[BaseModel]] = None,
        tags: typing.Optional[typing.List[str]] = None
):
    def decorator(f: typing.Callable) -> typing.Callable:
        f._swagger_info = SwaggerMethodInfo(responses, request, query, tags)
        return f
    return decorator


def setup_swagger(
    routes: typing.List[typing.Union[typing.Tuple[str, typing.Callable], tornado.web.URLSpec]],
    *,
    swagger_url: str = "/api/doc",
    api_base_url: str = "/",
    description: str = "Swagger API definition",
    api_version: str = "1.0.0",
    title: str = "Swagger API",
    contact: str = "",
    schemes: list = None,
    security_definitions: dict = None,
    security: list = None,
    display_models: bool = True,
    api_definition_version: str = API_SWAGGER_2,
    allow_cors: bool = False,
):
    """Inject swagger ui to application routes"""
    swagger_schema = generate_doc_from_endpoints(
        routes,
        api_base_url=api_base_url,
        description=description,
        api_version=api_version,
        title=title,
        contact=contact,
        schemes=schemes,
        security_definitions=security_definitions,
        security=security,
        api_definition_version=api_definition_version,
    )

    _swagger_ui_url = "/{}".format(swagger_url) if not swagger_url.startswith("/") else swagger_url
    _base_swagger_ui_url = _swagger_ui_url.rstrip("/")
    _swagger_spec_url = "{}/swagger.json".format(_swagger_ui_url)

    routes[:0] = [
        tornado.web.url(_swagger_ui_url, SwaggerUiHandler),
        tornado.web.url("{}/".format(_base_swagger_ui_url), SwaggerUiHandler),
        tornado.web.url(_swagger_spec_url, SwaggerSpecHandler),
    ]

    SwaggerSpecHandler.SWAGGER_SPEC = swagger_schema
    SwaggerSpecHandler.allow_cors = allow_cors
    SwaggerUiHandler.allow_cors = allow_cors

    with open(os.path.join(STATIC_PATH, "ui.html"), "r", encoding="utf-8") as f:
        SwaggerUiHandler.SWAGGER_HOME_TEMPLATE = (
            f.read().replace("{{ SWAGGER_URL }}", _swagger_spec_url).replace("{{ DISPLAY_MODELS }}", str(-1 if not display_models else 1))
        )
