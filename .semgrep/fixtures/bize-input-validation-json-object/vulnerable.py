from flask import request


def read_name():
    data = request.get_json()
    if not data:
        return {"error": "Body is required"}, 400
    name = data.get("name")
    return {"name": name}
