from flask import request


def read_name():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {"error": "Send a JSON object"}, 400
    name = data.get("name")
    return {"name": name}
