import json
from enum import Enum
from typing import Any, Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel, Field
from tornado import version_info
import tornado.ioloop
import tornado.options
import tornado.web

from tornado_swagger.const import API_OPENAPI_3_PYDANTIC
from tornado_swagger.setup import setup_swagger, swagger_decorator

T = TypeVar('T', bound=BaseModel)


class Tier2NestedItem(BaseModel):
    some_attribute: str


class NestedItem(BaseModel):
    item_name: str = Field(..., example="item_name")
    tier2_nested_item: Optional[Tier2NestedItem] = Field(None)


class NestedResponse(BaseModel):
    items: List[NestedItem] = Field(...)


class CalculusResponse(BaseModel):
    result: int = Field(..., example=42, description="This is result")
    you_are_cool: Optional[bool] = Field(None, description="Whether you're cool")


class CalculusQuery(BaseModel):
    i_am_cool: Optional[bool] = Field(None, description="Add this if you want to be cool")


class CalculusOperation(str, Enum):
    sum = "sum"
    subtract = "subtract"


class CalculusRequest(BaseModel):
    operation: CalculusOperation = Field(..., description="Operation")


class ErrorResponse(BaseModel):
    description: str = Field(..., example="error")


class NestedResponseHandler(tornado.web.RequestHandler):
    @swagger_decorator(
        responses={200: {"model": NestedResponse, "description": "Response with nested models"}},
        tags=["Nested"]
    )
    def get(self):
        # No output checks, but god will be sad if you won't follow your own notation
        self.write({"response": version_info})


class CalculusHandler(tornado.web.RequestHandler):
    @swagger_decorator(
        responses={
            # description can be skipped, in this case default description will be used
            200: {"model": CalculusResponse},
            400: {
                "model": ErrorResponse, "description": "Error will be raised for negative result"
            },
        },
        request=CalculusRequest,
        query=CalculusQuery,
        tags=["Calculus"]
    )
    def post(self, term_one: int, term_two: int):
        # still need to cast parameters to int. tornado gives zero fucks about your annotations
        term_one = int(term_one)
        term_two = int(term_two)

        query_params = self.request.arguments
        query_model = parse_query_params(query_params, CalculusQuery)

        body = self.request.body
        request_model = parse_body_params(body, CalculusRequest)

        if request_model.operation == CalculusOperation.sum:
            result = term_one + term_two
        elif request_model.operation == CalculusOperation.subtract:
            result = term_one - term_two
        else:
            # could never happen, just to make pycharm happy
            raise

        if result < 0:
            self.set_status(400)
            response = ErrorResponse(description="Why so negative")
            self.write(response.json())
            return
        response = CalculusResponse(result=result, you_are_cool=query_model.i_am_cool)
        self.write(response.json(exclude_none=True))


def parse_query_params(query_params: Dict[str, Any], model_type: Type[T]) -> T:
    flattened_params = {
        key: value[0].decode("utf-8") if isinstance(value, list) else value.decode("utf-8")
        for key, value in query_params.items()
    }
    return model_type(**flattened_params)


def parse_body_params(body: bytes, model_type: Type[T]) -> T:
    try:
        body_data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON body: {e}")

    return model_type(**body_data)


class Application(tornado.web.Application):
    _routes = [
        tornado.web.url(
            r"/term-one/(?P<term_one>[0-9\-]+)/term-two/(?P<term_two>[0-9\-]+)/sum",
            CalculusHandler
        ),
        tornado.web.url(r"/status", NestedResponseHandler),
        tornado.web.url(r"/static/(.*)", tornado.web.StaticFileHandler, {"path": "/var/www"}),
    ]

    def __init__(self):
        settings = {"debug": True}

        setup_swagger(
            self._routes,
            swagger_url="/doc",
            api_base_url="/",
            description="",
            api_version="1.0.0",
            title="test API",
            contact="name@domain",
            schemes=["https"],
            api_definition_version=API_OPENAPI_3_PYDANTIC,
        )
        super(Application, self).__init__(self._routes, **settings)


if __name__ == "__main__":
    tornado.options.define("port", default="8080", help="Port to listen on")
    tornado.options.parse_command_line()

    app = Application()
    app.listen(port=8080)

    tornado.ioloop.IOLoop.current().start()
