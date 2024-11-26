from pydantic import BaseModel, Field

class ExampleModel(BaseModel):
    name: str = Field(..., json_schema_extra={"example": "John Doe"})
    age: int = Field(..., json_schema_extra={"example": 30})

    class Config:
        schema_extra = {
            "example": {
                "name": "John Doe",
                "age": 30
            }
        }