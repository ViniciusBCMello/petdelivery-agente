from app import create_app
import logging

app = create_app()

logging.basicConfig(level=logging.INFO)
if __name__ == "__main__":
    app.run()