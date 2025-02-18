## This is a fork of the original tornado-swagger with pydantic support


## Usage

Too lazy to write documentation.

See examples/model_and_param_declaration_openapi3_pydantic.py for an example with complete set of available features

## Roadmap

- Multiple response models
- Request headers definition
- Raise error for different models with same names (now different model with same name of already registered model will be ignored)
- Fix nested models description handling (now if you add description to nested pydantic model, it will break componen ref)
