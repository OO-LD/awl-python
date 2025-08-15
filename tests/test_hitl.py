import asyncio
from enum import Enum
from typing import Any

from pydantic import Field

from awl.hitl import entry_point
from awl.hitl import hitl as human_in_the_loop
from oold.model import LinkedBaseModel


class MachineParams(LinkedBaseModel):
    """Parameters transferred to the machine"""

    model_config = {
        "json_schema_extra": {
            "required": ["param1"],
        },
    }
    param1: int = Field(50, ge=0, le=100)


class Quality(str, Enum):
    good = "Good"
    bad = "Bad"


class ProcessDocumentation(LinkedBaseModel):
    """Visual result inspection"""

    quality: Quality
    """Good is defined as..."""


@human_in_the_loop
def set_machine_params(params: MachineParams):
    # transfer params to machine
    return params


@human_in_the_loop
def document_result(params: ProcessDocumentation):
    # validate documentation
    return params


def archive_data(params: Any):
    # store documentation in database
    pass


@entry_point(gui=True)
def workflow():
    machine_params = set_machine_params()  # prompts user
    result_evaluation = document_result()  # prompts user
    print("Machine parameters: ", machine_params)
    print("Result evaluation: ", result_evaluation)
    archive_data(machine_params)  # runs automatically
    archive_data(result_evaluation)  # runs automatically


@entry_point(gui=True)
async def workflow_async():
    machine_params = set_machine_params()  # prompts user
    result_evaluation = document_result()  # prompts user
    print("Machine parameters: ", machine_params)
    print("Result evaluation: ", result_evaluation)
    archive_data(machine_params)  # runs automatically
    archive_data(result_evaluation)  # runs automatically


if __name__ == "__main__":
    # print(json.dumps(MachineParams.model_json_schema(), indent=2))
    # print(json.dumps(ProcessDocumentation.model_json_schema(), indent=2))
    workflow()
    asyncio.run(workflow_async())
