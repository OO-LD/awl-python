# decorator to generate the input of a function from console input

import asyncio
import functools
import inspect
import sys
import time

import panel as pn

from oold.model import LinkedBaseModel
from oold.model.v1 import LinkedBaseModel as LinkedBaseModel_v1
from oold.ui.panel import OoldEditor

jupyterlite = False
if sys.platform == "emscripten":
    # running in Pyodide or other Emscripten based build
    jupyterlite = True
    pn.extension(comms="ipywidgets")


class HitlApp(pn.viewable.Viewer):
    def __init__(self, **params):
        super().__init__(**params)

        self.message = pn.pane.Markdown(
            """This is a human-in-the-loop application.
            Please fill in the required fields and click 'Save' to proceed."""  # noqa
        )
        self.jsoneditor = OoldEditor(max_height=500, max_width=800)

        self.start_btn = pn.widgets.Button(
            css_classes=["start_btn"], name="Start", button_type="primary"
        )
        self.save_btn_clicked = False
        self.save_btn = pn.widgets.Button(
            css_classes=["save_btn"], name="Save", button_type="primary"
        )
        pn.bind(self.on_save, self.save_btn, watch=True)

        self._view = pn.Column(
            self.message,
            self.start_btn,
            self.jsoneditor,
            # display jsoneditor value in a JSON pane for debugging
            # pn.pane.JSON(self.jsoneditor.param.value, theme="light"),
            self.save_btn,
        )

    def on_save(self, event):
        # Handle the save event here
        self.save_btn_clicked = True

    def __panel__(self):
        return self._view


global ui
ui: HitlApp = None


def entry_point(gui: bool = False, jupyter: bool = False):
    """
    Decorator factory to initialize the OswEditor and
    serve it before entering a workflow entry point.
    Spins up a Panel server to display the UI and waits
    for it to be ready if option gui is true.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            global ui

            def cleanup():
                """
                Clean up the UI after the workflow is done.
                """
                global ui
                ui.message.object = "Workflow completed. You can close the web ui now."
                ui.jsoneditor.visible = False
                ui.save_btn.visible = False
                if not jupyter:
                    print("Stopping web ui...")

                    time.sleep(1)
                    server.stop()
                ui = None

            def run_threaded():  # func, *args, **kwargs):
                """
                Run the function in a separate thread to avoid blocking the main thread.
                """
                func(*args, **kwargs)
                cleanup()

            def run_async(event):
                """
                Run the function asynchronously.
                """
                import asyncio

                loop = asyncio.get_event_loop()
                # print("Running function asynchronously...")
                loop.run_in_executor(None, func, *args, **kwargs)
                # print("Function completed")
                cleanup()

            if gui and ui is None:
                # Initialize the OswEditor
                ui = HitlApp()

                if jupyter:
                    if jupyterlite:
                        ui.start_btn.on_click(run_async)
                        display(ui.servable())  # noqa
                    else:
                        # print("Running in Jupyter, using display() to show the UI.")
                        import threading

                        # thread = threading.Thread(target=func,
                        # args=args, kwargs=kwargs)
                        thread = threading.Thread(target=run_threaded)

                        # call ipython display function to show the UI
                        display(ui.servable())  # noqa

                        thread.start()
                        # thread.join()
                else:
                    print("Spinning up web ui...")
                    server = pn.serve(ui, threaded=True)

                    # wait for the UI to be ready
                    while not ui.jsoneditor.ready:
                        time.sleep(0.1)
                    # print("Web ui is ready.")

            if jupyter:
                # run the function in a thread to avoid blocking the Jupyter notebook
                print(
                    "Running in Jupyter, executing the function in a separate thread."
                )
                result = None
                # result = func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            # Clean up after the workflow is done
            if gui and not jupyter:
                cleanup()

            return result

        async def async_wrapper(*args, **kwargs):
            global ui

            def cleanup():
                """
                Clean up the UI after the workflow is done.
                """
                global ui
                ui.message.object = "Workflow completed. You can close the web ui now."
                ui.jsoneditor.visible = False
                ui.save_btn.visible = False
                if not jupyter:
                    print("Stopping web ui...")

                    time.sleep(1)
                    server.stop()
                ui = None

            def run_threaded():  # func, *args, **kwargs):
                """
                Run the function in a separate thread to avoid blocking the main thread.
                """
                asyncio.run(func(*args, **kwargs))
                cleanup()

            async def run_async(event=None):
                """
                Run the function asynchronously.
                """
                ui.jsoneditor.visible = True
                ui.save_btn.visible = True
                ui.start_btn.visible = False
                # import asyncio

                # loop = asyncio.get_event_loop()
                print("Running function asynchronously...")
                # loop.run_in_executor(None, func, *args, **kwargs)
                result = await func(*args, **kwargs)
                print("Function completed")
                cleanup()
                return result

            # if gui and ui is None:
            if gui:
                # Initialize the OswEditor
                ui = HitlApp()

                if jupyter:
                    if jupyterlite:
                        ui.jsoneditor.visible = False
                        ui.save_btn.visible = False
                        ui.start_btn.on_click(run_async)
                        # await run_async()
                        display(ui.servable())  # noqa
                    else:
                        # print("Running in Jupyter, using display() to show the UI.")
                        import threading

                        # thread = threading.Thread(
                        # target=func, args=args, kwargs=kwargs
                        # )
                        thread = threading.Thread(target=run_threaded)

                        # call ipython display function to show the UI
                        display(ui.servable())  # noqa

                        thread.start()
                        # # thread.join()
                        # # ui.jsoneditor.visible = False
                        # # ui.save_btn.visible = False
                        # ui.start_btn.on_click(run_async)
                        # #await run_async()
                        # display(ui.servable())  # noqa
                        # print("After display")
                        # #result = await run_async()
                else:
                    print("Spinning up web ui...")
                    # ui.start_btn.on_click(run_async)
                    server = pn.serve(ui, threaded=True)
                    result = await run_async()
                    # server = pn.serve(ui, threaded=False)
                    # wait for the UI to be ready
                    # while not ui.jsoneditor.ready:
                    #     time.sleep(0.1)
                    # print("Web ui is ready.")

            if jupyter:
                # run the function in a thread
                # to avoid blocking the Jupyter notebook
                print(
                    """Running in Jupyter, executing the function
                    in a separate thread."""
                )
                result = None
                # result = func(*args, **kwargs)
            # else:
            #    result = func(*args, **kwargs)

            # Clean up after the workflow is done
            # if gui and not jupyter:
            #    cleanup()

            return result

        # return wrapper depending on whether we want async or not
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return wrapper

    return decorator


def hitl(func):
    """
    Decorator to generate the input of a function from console input.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Get the function's signature
        signature = inspect.signature(func)

        # Prepare a dictionary to hold the inputs
        inputs = {}
        global ui
        # Iterate over the parameters in the signature
        # ToDo: DataClass or Pydantic model support
        for param in signature.parameters.values():
            # if parameter is a OOLD model run a jsoneditor
            if issubclass(param.annotation, LinkedBaseModel) or issubclass(
                param.annotation, LinkedBaseModel_v1
            ):
                # If parameter is a model, use the OswEditor to get the value
                if ui is None:
                    ui = HitlApp()
                    pn.serve(ui, threaded=True)
                # wait for the UI to be ready
                while not ui.jsoneditor.ready:
                    # print("Waiting for JSONEditor to be ready...")
                    time.sleep(0.1)
                # print("Setting schema for parameter: ", param.name)
                ui.jsoneditor.set_schema(param.annotation.model_json_schema())

                while not ui.save_btn_clicked:
                    # print("Waiting for user input...")
                    time.sleep(0.1)
                ui.save_btn_clicked = False  # reset the button state
                inputs[param.name] = param.annotation(**ui.jsoneditor.get_value())
                # continue
            elif param.default is param.empty:
                # If parameter has no default, prompt for input
                user_input = input(
                    f"Enter value for {param.name} ({param.annotation}): "
                )
                inputs[param.name] = user_input
            else:
                # If parameter has a default, use it
                inputs[param.name] = param.default

        # Call the original function with the collected inputs
        return func(*inputs.values())

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        # Get the function's signature
        signature = inspect.signature(func)

        # Prepare a dictionary to hold the inputs
        inputs = {}
        global ui
        # Iterate over the parameters in the signature
        # ToDo: DataClass or Pydantic model support
        for param in signature.parameters.values():
            # if parameter is a OOLD model run a jsoneditor
            if issubclass(param.annotation, LinkedBaseModel) or issubclass(
                param.annotation, LinkedBaseModel_v1
            ):
                # If parameter is a model, use the OswEditor to get the value
                if ui is None:
                    ui = HitlApp()
                    pn.serve(ui, threaded=True)
                # wait for the UI to be ready
                while not ui.jsoneditor.ready:
                    # print("Waiting for JSONEditor to be ready...")
                    await asyncio.sleep(0.1)
                # print("Setting schema for parameter: ", param.name)
                ui.jsoneditor.set_schema(param.annotation.model_json_schema())

                while not ui.save_btn_clicked:
                    # print("Waiting for user input...")
                    await asyncio.sleep(0.1)
                ui.save_btn_clicked = False  # reset the button state
                inputs[param.name] = param.annotation(**ui.jsoneditor.get_value())
                # continue
            elif param.default is param.empty:
                # If parameter has no default, prompt for input
                user_input = input(
                    f"Enter value for {param.name} ({param.annotation}): "
                )
                inputs[param.name] = user_input
            else:
                # If parameter has a default, use it
                inputs[param.name] = param.default

        # Call the original function with the collected inputs
        if asyncio.iscoroutinefunction(func):
            return await func(*inputs.values())
        else:
            return func(*inputs.values())

    # return wrapper depending on whether we want async or not
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return wrapper


# Example usage
@hitl
def example_function(name: str, age: int = 30):
    print(f"Name: {name}, Age: {age}")
