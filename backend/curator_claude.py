"""One Claude Messages API call, run inside /opt/vernis/curator-venv.

The anthropic SDK needs newer packages than Debian ships for the system
Python that runs Vernis, so curator.py calls this helper in its own venv:
JSON request on stdin ({"api_key", "request"}), JSON response on stdout.
"""

import json
import sys

import anthropic


def main():
    data = json.load(sys.stdin)
    client = anthropic.Anthropic(api_key=data["api_key"], max_retries=2)
    try:
        response = client.beta.messages.create(**data["request"])
    except anthropic.AuthenticationError:
        out = {"error": "The Claude API key was rejected."}
    except anthropic.PermissionDeniedError:
        out = {"error": "This Claude API key lacks permission for that model."}
    except anthropic.NotFoundError as e:
        out = {"error": f"Claude model not found: {e.message}"}
    except anthropic.RateLimitError:
        out = {"error": "Claude is rate limiting this key. Try again in a minute."}
    except anthropic.APIStatusError as e:
        out = {"error": f"Claude API error {e.status_code}: {e.message}"}
    except anthropic.APIConnectionError:
        out = {"error": "Could not reach the Claude API."}
    else:
        out = {"response": response.model_dump(mode="json", exclude_none=True)}
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    if sys.argv[1:] == ["models"]:
        key = json.load(sys.stdin)["api_key"]
        try:
            ids = [m.id for m in anthropic.Anthropic(api_key=key).models.list()]
            json.dump({"models": ids}, sys.stdout)
        except anthropic.APIError as e:
            json.dump({"error": f"{type(e).__name__}: {getattr(e, 'message', e)}"}, sys.stdout)
    else:
        main()
