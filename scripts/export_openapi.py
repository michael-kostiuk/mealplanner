import json
import os
import sys

# Set a memory DATABASE_URL if not provided, as main.py tries to create tables on import
if not os.getenv("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# Add the root directory to sys.path to allow importing from 'app'
# This ensures that even if run from inside 'scripts/', it can find the 'app' module.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from app.main import app
except ImportError as e:
    print(
        f"Error: Could not import 'app'. Make sure you are running this from the project root or it is in your PYTHONPATH. {e}"
    )
    sys.exit(1)
except Exception as e:
    print(f"Error during app initialization: {e}")
    sys.exit(1)


def export_openapi(output_file="openapi.json"):
    """
    Exports the FastAPI app OpenAPI schema to a JSON file.
    """
    # Generate the OpenAPI schema
    openapi_schema = app.openapi()

    # Path relative to the script location (in the project root)
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    output_path = os.path.join(root_dir, output_file)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2, ensure_ascii=False)

    print(f"OpenAPI schema successfully exported to: {output_path}")


if __name__ == "__main__":
    export_openapi()
