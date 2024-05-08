import os
import json
from pathlib import Path

from chgksuite.common import get_source_dirs
from chgksuite.version import __version__

_, resourcedir = get_source_dirs()

ui_json = json.loads((Path(resourcedir) / "ui_gen.json").read_text())

PREFIX = f"""\
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="{{{{ url_for('static', filename='water.css') }}}}">
</head>
<body>
<h1>chgksuite v{__version__}</h1>
<form>
"""
SUFFIX = """</body></html>"""
ADVANCED_STUB = """\
<input type="submit" value="Запустить">
<details>
    <summary>Дополнительные настройки</summary>
    {content}
</details>
</form>
"""
FILEPICKER_STUB = """\
<label for="{id_}"></label>{caption} ({extensions})<input
    type="file"
    id="{id_}"
    accept="{extensions}" />
"""
CHECKBOX_STUB = """\
<input id="{id_}" type="checkbox"><label for="{id_}">{caption}</label>
"""
DROPDOWN_STUB = """\
<label for="{id_}">Действие:</label><select id="{id_}">
    <option value="">--Выберите вариант--</option>
    {options}
</select>
"""


class UiNode:
    def __init__(self, json_, parent=None):
        self.json = json_
        self.parent = parent
        self.children = []
        self.name = json_["name"]
        _parent = self.parent
        while _parent:
            self.name = _parent.name + "___" + self.name
            _parent = _parent.parent
        self.main_frame = []
        self.advanced_frame = []

    def gen_id(self, name):
        return self.name + "___" + name

    def build(self):
        for param in self.json.get("params") or []:
            if param.get("advanced"):
                frame = self.advanced_frame
            else:
                frame = self.main_frame
            caption = param.get("caption") or param.get("name")
            id_ = self.gen_id(param["name"])
            if param["type"] == "filepicker":
                frame.append(
                    FILEPICKER_STUB.format(
                        id_=id_, caption=caption, extensions=param["extensions"]
                    )
                )
            elif param["type"] == "checkbox":
                frame.append(CHECKBOX_STUB.format(id_=id_, caption=caption))
        commands = []
        for command in self.json.get("commands") or []:
            node = UiNode(command, parent=self)
            self.children.append(node)
            commands.append(command["name"])
            node.build()
            if node.main_frame:
                self.main_frame.extend(node.main_frame)
            if node.advanced_frame:
                self.advanced_frame.extend(node.advanced_frame)
        if commands:
            id_ = self.gen_id("action")
            options = [
                f"""<option value="{command}">{command}</option>"""
                for command in commands
            ]
            self.main_frame = [
                DROPDOWN_STUB.format(id_=id_, options="\n    ".join(options))
            ] + self.main_frame

    def render(self):
        if self.parent:
            raise NotImplementedError
        main = "\n".join(self.main_frame)
        advanced = ADVANCED_STUB.format(content="\n".join(self.advanced_frame))
        return PREFIX + main + advanced + SUFFIX


def render_ui():
    root_node = UiNode(ui_json)
    root_node.build()
    return root_node.render()

