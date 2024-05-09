import os
import json
from pathlib import Path

from chgksuite.common import get_source_dirs
from chgksuite.version import __version__

_, resourcedir = get_source_dirs()

ui_json = json.loads((Path(resourcedir) / "ui_gen.json").read_text())

PREFIX = """\
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="{{ url_for('static', filename='water.css') }}">
    <script>
        all_div_elements = {all_div_elements};
        function stripSuffix(inputString, suffix) {
            if (inputString.endsWith(suffix)) {
                return inputString.slice(0, -suffix.length);
            }
            return inputString;
        };
        function goodnessCheck(divId, goodDivId) {
            parts = divId.split(".");
            return goodDivId.startsWith(parts[0]);
        };
        function hideDivsExcept(goodDivId) {
            for (divId of all_div_elements) {
                if (goodnessCheck(divId, goodDivId)) {
                    document.getElementById(divId).style.display = "block";
                } else {
                    document.getElementById(divId).style.display = "none";
                }
            }
        };
        action_dropdowns = {action_dropdowns};
        window.addEventListener("load", function() {
            hideDivsExcept("asldfalkdjf");
            for (dropdown of action_dropdowns)  {
                selector = document.getElementById(dropdown);
                selector.addEventListener(
                    "change", function() {
                        goodDivId = stripSuffix(dropdown, '.select') + '___' + selector.value;
                        console.log(goodDivId);
                        hideDivsExcept(goodDivId)
                    }
                );
            };
        });
    </script>
</head>
<body>
<h1>chgksuite v{__version__}</h1>
<form action="/" method="post" enctype="multipart/form-data">
""".replace("{__version__}", __version__)

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
    name="{id_}"
    accept="{extensions}" /><br>
"""
CHECKBOX_STUB = """\
<input id="{id_}" name="{id_}" type="checkbox"><label for="{id_}">{caption}</label><br>
"""
TEXT_STUB = """<label for="{id_}">{caption}</label><input id="{id_}" name="{id_}" value="{value}"><br>"""
MANDATORY_CHOOSE = """<option value="">--Выберите вариант--</option><br>"""
DROPDOWN_STUB = """\
<label for="{id_}">{caption}:</label><select id="{id_}" name="{id_}">
    {mandatory_choose}
    {options}
</select><br>
"""

def make_options(options):
    return "\n    ".join("""<option value="{option}">{option}</option>""".format(option=option) for option in options)

"""
// JavaScript function that executes when user selects a value in a dropdown

function handleDropdownChange(event) {
    const selectedValue = event.target.value;
    // Do something with the selected value, for example:
    console.log("Selected value: " + selectedValue);
}

// Assuming you have a dropdown element with the id "myDropdown"
const dropdown = document.getElementById("myDropdown");
dropdown.addEventListener("change", handleDropdownChange);

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
        self.all_div_elements = []
        self.action_selectors = []

    def get_root(self):
        if not self.parent:
            return self
        _parent = self.parent
        while _parent:
            _parent = _parent.parent
        return _parent

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
            elif param["type"] == "dropdown":
                frame.append(
                    DROPDOWN_STUB.format(
                        id_=id_, caption=caption, options=make_options(param["choices"]), mandatory_choose=""
                    )
                )
            elif param["type"] == "text":
                frame.append(
                    TEXT_STUB.format(
                        id_=id_,
                        caption=caption,
                        value=param.get("default") or "",
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
            root = self.get_root()
            prefix = [f"""<div id="{node.name}">"""]
            adv_prefix = [f"""<div id="{node.name}.advanced">"""]
            suffix = ["</div>"]
            if node.main_frame:
                self.main_frame.extend(prefix + node.main_frame + suffix)
                root.all_div_elements.append(node.name)
            if node.advanced_frame:
                self.advanced_frame.extend(adv_prefix + node.advanced_frame + suffix)
                root.all_div_elements.append(node.name + ".advanced")
        if commands:
            id_ = self.name + (".select")
            self.get_root().action_selectors.append(id_)
            self.main_frame = [
                DROPDOWN_STUB.format(id_=id_, options=make_options(commands), caption=self.json["caption"], mandatory_choose=MANDATORY_CHOOSE)
            ] + self.main_frame

    def render(self):
        if self.parent:
            raise NotImplementedError
        prefix = PREFIX.replace("{all_div_elements}", json.dumps(self.all_div_elements)).replace(
            "{action_dropdowns}", json.dumps(self.action_selectors)
        )
        main = "\n".join(self.main_frame)
        advanced = ADVANCED_STUB.format(content="\n".join(self.advanced_frame))
        return prefix + main + advanced + SUFFIX


def render_ui():
    root_node = UiNode(ui_json)
    root_node.build()
    return root_node.render()

