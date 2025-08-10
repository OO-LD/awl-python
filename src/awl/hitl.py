# decorator to generate the input of a function from console input

import functools
import inspect
import time

import panel as pn

from oold.model import LinkedBaseModel
from oold.model.v1 import LinkedBaseModel as LinkedBaseModel_v1
from oold.ui.panel.anywidget_vite.jsoneditor import OswEditor


class HitlApp(pn.viewable.Viewer):
    def __init__(self, **params):
        super().__init__(**params)

        self.message = pn.pane.Markdown(
            """This is a human-in-the-loop application.
            Please fill in the required fields and click 'Save' to proceed."""  # noqa
        )
        self.jsoneditor = OswEditor(max_height=500, max_width=800)

        self.save_btn_clicked = False
        self.save_btn = pn.widgets.Button(
            css_classes=["save_btn"], name="Save", button_type="primary"
        )
        pn.bind(self.on_save, self.save_btn, watch=True)

        self._view = pn.Column(
            self.message,
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

            if gui and ui is None:
                # Initialize the OswEditor
                ui = HitlApp()

                if jupyter:
                    # print("Running in Jupyter, using display() to show the UI.")
                    import threading

                    # thread = threading.Thread(target=func, args=args, kwargs=kwargs)
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

    return wrapper


# Example usage
@hitl
def example_function(name: str, age: int = 30):
    print(f"Name: {name}, Age: {age}")
