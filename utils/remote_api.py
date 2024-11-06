import requests
from typing import Any


class RemoteAPI:
    def __init__(self, bf_version: int):
        self._remote_url = f"https://downloaders.azurewebsites.net/downloaders/bluefield{bf_version}_fw_downloader/helper.php"

    def get_latest_version(self) -> str:
        data = {
            "action": "get_versions",
        }
        response = requests.post(self._remote_url, data=data)
        s = response.json()["latest"]
        assert isinstance(s, str)
        return s

    def get_distros(self, v: str) -> Any:
        data = {
            "action": "get_distros",
            "version": v,
        }
        r = requests.post(self._remote_url, data=data)
        return r.json()

    def get_os(self, version: str, distro: str) -> Any:
        data = {
            "action": "get_oses",
            "version": version,
            "distro": distro,
        }
        r = requests.post(self._remote_url, data=data)
        return r.json()[0]

    def get_download_info(self, version: str, distro: str, os_param: str) -> Any:
        data = {
            "action": "get_download_info",
            "version": version,
            "distro": distro,
            "os": os_param,
            "arch": "x64",
        }
        r = requests.post(self._remote_url, data=data)
        return r.json()
