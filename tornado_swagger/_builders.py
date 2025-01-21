# pylint: disable=R0401,C0415
"""Builders"""
import abc
import collections
import inspect
import os
import re
import typing
import warnings

from pydantic import BaseModel
import tornado.web
import yaml

from tornado_swagger.const import API_OPENAPI_3, API_SWAGGER_2, API_OPENAPI_3_PYDANTIC

SWAGGER_TEMPLATE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "templates", "swagger.yaml")
)
SWAGGER_DOC_SEPARATOR = "---"


PYTHON_TO_OPENAPI_MAPPER = {
    int: {"type": "integer", "format": "int32"},
    float: {"type": "number", "format": "float"},
    str: {"type": "string"},
    bool: {"type": "boolean"},
    list: {"type": "array", "items": {}},
    dict: {"type": "object"},
    None: {"nullable": True},
    bytes: {"type": "string", "format": "byte"},
    complex: {"type": "number", "format": "double"},
}


def input_parameters_getter(
        some_callable: typing.Callable
) -> typing.List[typing.Dict[str, typing.Type]]:
    """Parse handler input parameters"""
    signature = inspect.signature(some_callable)
    parameters = []

    for name, param in signature.parameters.items():
        if name in ("self", "cls"):
            continue

        parameters.append({"name": name, "type": param.annotation})

    return parameters


def _extract_swagger_definition(endpoint_doc: str):
    """Extract swagger definition after SWAGGER_DOC_SEPARATOR"""
    endpoint_doc = endpoint_doc.splitlines()

    for i, doc_line in enumerate(endpoint_doc):
        if SWAGGER_DOC_SEPARATOR in doc_line:
            end_point_swagger_start = i + 1
            endpoint_doc = endpoint_doc[end_point_swagger_start:]
            break
    return "\n".join(endpoint_doc)


def build_swagger_docs(endpoint_doc: str):
    """Build swagger doc based on endpoint docstring"""
    endpoint_doc = _extract_swagger_definition(endpoint_doc)

    # Build JSON YAML Obj
    try:
        endpoint_doc = endpoint_doc.replace("\t", "    ")  # fix windows tabs bug
        end_point_swagger_doc = yaml.safe_load(endpoint_doc)
        if not isinstance(end_point_swagger_doc, dict):
            raise yaml.YAMLError()
        return end_point_swagger_doc
    except yaml.YAMLError:
        return {
            "description": "Swagger document could not be loaded from docstring",
            "tags": ["Invalid Swagger"],
        }


def _try_extract_doc(func):
    """Extract docstring from origin function removing decorators"""
    return inspect.unwrap(func).__doc__


def _build_doc_from_func_doc(handler):
    out = {}

    for method in handler.SUPPORTED_METHODS:
        method = method.lower()
        doc = _try_extract_doc(getattr(handler, method))

        if doc is not None and "---" in doc:
            out.update({method: build_swagger_docs(doc)})

    return out


class PydanticRoutesProcessor:
    def __init__(self):
        self.paths = collections.defaultdict(dict)
        self.components = {
                "schemas": {},
                "parameters": {},
            }

    def extract_paths_pydantic(self, routes):
        for route in routes:
            for method_name, method_description in self._build_doc_from_pydantic_handler(
                    route.target
            ).items():
                path_handler = _format_handler_path(route, method_name)
                if path_handler is None:
                    continue

                self.paths[path_handler].update({method_name: method_description})

        return self.paths, self.components

    def _build_doc_from_pydantic_handler(self, handler):
        out = {}

        for method_name in handler.SUPPORTED_METHODS:
            method_name = method_name.lower()
            method_callable = getattr(handler, method_name)
            is_swagger_handler = getattr(method_callable, "_is_swagger_handler", False)
            if is_swagger_handler:
                response_models = getattr(method_callable, "_response_models", None)
                request_model = getattr(method_callable, "_request_model", None)
                query_params = getattr(method_callable, "_query_params", None)
                tags = getattr(method_callable, "_swagger_tags", None)
                input_parameters = input_parameters_getter(method_callable)
                out.update(
                    {
                        method_name: self.build_pydantic_docs(
                            input_parameters, response_models, request_model, query_params, tags,
                        )
                    }
                )

        return out

    def _add_components_from_definitions(self, definitions: typing.Dict[str, typing.Any]):
        # could cause conflicts for classes with same name
        for definition_name, definition_spec in definitions.items():
            if definition_name not in self.components["schemas"]:
                self.components["schemas"][definition_name] = definition_spec

    @staticmethod
    def _generate_default_description(status_code: int) -> str:
        if status_code < 400:
            return "Successful Response"
        elif status_code < 500:
            return "Bad request"
        return "Internal Server Error"

    def build_pydantic_docs(
        self,
        input_parameters: typing.List[typing.Dict[str, typing.Any]],
        response_models: typing.Dict[int, typing.Dict[str, typing.Any]],
        request: typing.Optional[typing.Type[BaseModel]] = None,
        query: typing.Optional[typing.Type[BaseModel]] = None,
        tags: typing.Optional[typing.List[str]] = None,
    ):
        result = {}

        parameters = self._build_input_and_query_doc(input_parameters, query)
        if parameters:
            result["parameters"] = parameters

        if request:
            model_spec = request.schema(ref_template="#/components/schemas/{model}")
            if "definitions" in model_spec:
                self._add_components_from_definitions(model_spec.pop("definitions"))

            result["requestBody"] = {
                "content": {
                    "application/json": {
                        "schema": model_spec
                    }
                },
                "required": True
            }

        responses = {}
        for status_code, response_model in response_models.items():
            model = response_model["model"]
            description = response_model.get("description", None)
            if not description:
                description = self._generate_default_description(status_code)
            model_spec = model.schema(ref_template="#/components/schemas/{model}")
            model_name = model.__name__
            # could cause conflicts for classes with same name
            if model_name not in self.components["schemas"]:
                self.components["schemas"][model_name] = model_spec

            if "definitions" in model_spec:
                self._add_components_from_definitions(model_spec.pop("definitions"))

            responses[status_code] = {
                "description": description,
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{model_name}"},
                    }
                }
            }

        result["responses"] = responses

        if tags:
            result["tags"] = tags
        return result

    @staticmethod
    def _build_request_body_doc(model: BaseModel) -> dict:
        model_schema = model.schema(ref_template="#/components/schemas/{model}")

        request_body = {
            "content": {
                "application/json": {
                    "schema": model_schema
                }
            },
            "required": True
        }

        return request_body

    @staticmethod
    def _build_input_and_query_doc(
        input_parameters: typing.List[typing.Dict[str, typing.Any]],
        query: typing.Optional[typing.Type[BaseModel]] = None,
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        parameters = []

        if input_parameters:
            for input_parameter in input_parameters:
                parameters.append({
                    "in": "path",
                    "required": True,
                    "name": input_parameter["name"],
                    "schema": PYTHON_TO_OPENAPI_MAPPER[input_parameter["type"]],
                })

        if query:
            query_schema = query.schema()
            for parameter_name, schema in query_schema["properties"].items():
                parameters.append({
                    "in": "query",
                    "required": parameter_name in query_schema.get("required", []),
                    "name": parameter_name,
                    "schema": schema,
                })

        return parameters


def _try_extract_args(method_handler):
    """Extract method args from origin function removing decorators"""
    return inspect.getfullargspec(inspect.unwrap(method_handler)).args[1:]


def _extract_parameters_names(handler, parameters_count, method):
    """Extract parameters names from handler"""
    if parameters_count == 0:
        return []

    parameters = ["{?}" for _ in range(parameters_count)]

    method_handler = getattr(handler, method.lower())
    args = _try_extract_args(method_handler)

    for i, arg in enumerate(args):
        if set(arg) != {"_"} and i < len(parameters):
            parameters[i] = arg

    return parameters


def _format_handler_path(route, method):
    brackets_regex = re.compile(r"\(.*?\)")
    parameters = _extract_parameters_names(route.target, route.regex.groups, method)
    route_pattern = route.regex.pattern
    brackets = brackets_regex.findall(route_pattern)

    if len(brackets) != len(parameters):
        warnings.warn("Illegal route. route.regex.groups does not match all parameters. Route = " + str(route))
        return None

    for i, entity in enumerate(brackets):
        route_pattern = route_pattern.replace(entity, "{%s}" % parameters[i], 1)

    return route_pattern[:-1]


def nesteddict2yaml(d, indent=10, result=""):
    for key, value in d.items():
        result += " " * indent + str(key) + ":"
        if isinstance(value, dict):
            result = nesteddict2yaml(value, indent + 2, result + "\n")
        else:
            result += " " + str(value) + "\n"
    return result


def _clean_description(description: str):
    """Remove empty space from description begin"""
    _start_desc = 0
    for i, word in enumerate(description):
        if word != "\n":
            _start_desc = i
            break
    return "    ".join(description[_start_desc:].splitlines())


def _extract_paths(routes):
    paths = collections.defaultdict(dict)

    for route in routes:
        for method_name, method_description in _build_doc_from_func_doc(route.target).items():
            path_handler = _format_handler_path(route, method_name)
            if path_handler is None:
                continue

            paths[path_handler].update({method_name: method_description})

    return paths


class BaseDocBuilder(abc.ABC):
    """Doc builder"""

    @property
    @abc.abstractmethod
    def schema(self):
        """Supported Schema"""

    @abc.abstractmethod
    def generate_doc(
        self,
        routes: typing.List[tornado.web.URLSpec],
        *,
        api_base_url,
        description,
        api_version,
        title,
        contact,
        schemes,
        security_definitions,
        security,
        models,
        parameters
    ):
        """Generate docs"""


class Swagger2DocBuilder(BaseDocBuilder):
    """Swagger2.0 schema builder"""

    @property
    def schema(self):
        """Supported Schema"""
        return API_SWAGGER_2

    def generate_doc(
        self,
        routes: typing.List[tornado.web.URLSpec],
        *,
        api_base_url,
        description,
        api_version,
        title,
        contact,
        schemes,
        security_definitions,
        security,
        models,
        parameters
    ):
        """Generate docs"""
        swagger_spec = {
            "swagger": "2.0",
            "info": {
                "title": title,
                "description": _clean_description(description),
                "version": api_version,
            },
            "basePath": api_base_url,
            "schemes": schemes,
            "definitions": models,
            "parameters": parameters,
            "paths": _extract_paths(routes),
        }
        if contact:
            swagger_spec["info"]["contact"] = {"name": contact}
        if security_definitions:
            swagger_spec["securityDefinitions"] = security_definitions
        if security:
            swagger_spec["security"] = security

        return swagger_spec


class OpenApiDocBuilder(BaseDocBuilder):
    """OpenAPI 3 Schema builder"""

    @property
    def schema(self):
        """Supported Schema"""
        return API_OPENAPI_3

    def generate_doc(
        self,
        routes: typing.List[tornado.web.URLSpec],
        *,
        api_base_url,
        description,
        api_version,
        title,
        contact,
        schemes,
        security_definitions,
        security,
        models,
        parameters
    ):
        """Generate docs"""
        swagger_spec = {
            "openapi": "3.0.3",
            "info": {
                "title": title,
                "description": _clean_description(description),
                "version": api_version,
            },
            "servers": [{"url": api_base_url}],
            "components": {
                "schemas": models,
                "parameters": parameters,
            },
            "paths": _extract_paths(routes),
        }

        if contact:
            swagger_spec["info"]["contact"] = {"name": contact}
        if security_definitions:
            swagger_spec["securityDefinitions"] = security_definitions
        if security:
            swagger_spec["security"] = security

        return swagger_spec


class PydanticBuilder(BaseDocBuilder):
    """OpenAPI 3 Schema builder with pydantic support"""

    @property
    def schema(self):
        """Supported Schema"""
        return API_OPENAPI_3_PYDANTIC

    def generate_doc(
        self,
        routes: typing.List[tornado.web.URLSpec],
        *,
        api_base_url,
        description,
        api_version,
        title,
        contact,
        schemes,
        security_definitions,
        security,
        models,
        parameters
    ):
        """Generate docs"""
        swagger_spec = {
            "openapi": "3.0.3",
            "info": {
                "title": title,
                "description": _clean_description(description),
                "version": api_version,
            },
            "servers": [{"url": api_base_url}],
        }
        routes_processor = PydanticRoutesProcessor()
        paths, components = routes_processor.extract_paths_pydantic(routes)
        swagger_spec["components"] = components
        swagger_spec["paths"] = paths

        if contact:
            swagger_spec["info"]["contact"] = {"name": contact}
        if security_definitions:
            swagger_spec["securityDefinitions"] = security_definitions
        if security:
            swagger_spec["security"] = security

        return swagger_spec


doc_builders = {b.schema: b for b in [Swagger2DocBuilder(), OpenApiDocBuilder(), PydanticBuilder()]}


def generate_doc_from_endpoints(
    routes: typing.List[tornado.web.URLSpec],
    *,
    api_base_url,
    description,
    api_version,
    title,
    contact,
    schemes,
    security_definitions,
    security,
    api_definition_version
):
    """Generate doc based on routes"""
    from tornado_swagger.model import export_swagger_models
    from tornado_swagger.parameter import export_swagger_parameters

    if api_definition_version not in doc_builders:
        raise ValueError("Unknown api_definition_version = " + api_definition_version)

    return doc_builders[api_definition_version].generate_doc(
        routes,
        api_base_url=api_base_url,
        description=description,
        api_version=api_version,
        title=title,
        contact=contact,
        schemes=schemes,
        security_definitions=security_definitions,
        security=security,
        models=export_swagger_models(),
        parameters=export_swagger_parameters(),
    )
