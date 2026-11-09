from aiohttp import web

from inventory_api.app import create_app
from shared.config import api_host, api_port


def main() -> None:
    web.run_app(create_app(), host=api_host(), port=api_port())


if __name__ == "__main__":
    main()
