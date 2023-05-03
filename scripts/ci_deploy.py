import logging
import os
import requests
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from requests.models import HTTPError


repo_url = "https://api.github.com/repos/b-src/bg-xyz/actions/artifacts"
home_path = Path("/home/ci_deploy")
artifact_timestamp_file_path = home_path / "last_deployed_time.txt"
deploy_path = home_path / "sites"
token_path = Path("/usr/local/share/ci_deploy/ci_deploy_token.txt")


def configure_logging() -> logging.Logger:
    log_handler = logging.StreamHandler(sys.stdout)
    log_handler.setLevel(logging.INFO)
    formatter = logging.Formatter("%(levelname)s - %(message)s")
    log_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[log_handler])
    return logging.getLogger("ci_deploy script")


logger = configure_logging()


def get_token_from_file(token_file_path: Path) -> str:
    token = ""
    try:
        with open(token_file_path, "r") as tf:
            token = tf.read().strip()

    except FileNotFoundError as e:
        logger.critical("Token file not found at %s: %s", token_file_path, str(e))
    except PermissionError as e:
        logger.critical("Invalid permissions for %s: %s", token_file_path, str(e))

    return token


def get_latest_artifact(repo_url: str) -> Dict[str, Any]:
    latest_artifact = {}
    artifacts = requests.get(url=repo_url).json()["artifacts"]
    if artifacts:
        latest_artifact = artifacts[0]

    return latest_artifact


def get_previous_artifact_time() -> datetime:
    previous_time = datetime.min
    if os.path.isfile(artifact_timestamp_file_path):
        with open(artifact_timestamp_file_path, "r") as f:
            previous_time = datetime.strptime(f.read().strip(), "%Y-%m-%dT%H:%M:%SZ")

    return previous_time


def set_previous_artifact_time(artifact_time: datetime) -> None:
    logger.info("Updating deployed artifact timestamp")
    with open(artifact_timestamp_file_path, "w") as f:
        f.write(artifact_time.strftime("%Y-%m-%dT%H:%M:%SZ"))


def artifact_is_new(artifact_created_time: datetime) -> bool:
    last_deploy_time = get_previous_artifact_time()
    return artifact_created_time > last_deploy_time


def deploy_artifact(artifact_download_url: str, artifact_created_time: datetime) -> None:
    file_name = home_path / f"artifact_{datetime.strftime(artifact_created_time, '%m_%d_%Y_%H_%M_%S')}.zip"
    logger.info("Downloading %s", artifact_download_url)
    try:
        token = get_token_from_file(token_path)
        artifact_zip = requests.get(url=artifact_download_url, headers = {"Authorization": f"token: {token}"})
        artifact_zip.raise_for_status()
        with open(file_name, "wb") as f:
            f.write(artifact_zip.content)

        if deploy_path.exists():
            logger.info("Removing existing deployment")
            shutil.rmtree(deploy_path)

        deploy_path.mkdir()
        logger.info("Unzipping new artifact into %s", deploy_path)
        shutil.unpack_archive(str(file_name), str(deploy_path))
        logger.info("Deployment successful")

        set_previous_artifact_time(artifact_created_time)

        logger.info("Deleting downloaded artifact at %s", file_name)
        file_name.unlink()
    except HTTPError as e:
        logger.error("Error downloading artifact: %s", e)


if __name__ == "__main__":
    try:
        logger.info("Running site deployment script")
        latest_artifact = get_latest_artifact(repo_url)
        artifact_created_time = datetime.strptime(latest_artifact["created_at"], "%Y-%m-%dT%H:%M:%SZ")

        if artifact_is_new(artifact_created_time):
            if latest_artifact["expired"] == True:
                logger.error("Latest artifact is newer than deployed artifact but is expired and cannot be deployed")
            else:
                logger.info("New artifact found, deploying")
                artifact_download_url = latest_artifact["archive_download_url"]
                deploy_artifact(artifact_download_url, artifact_created_time)
        else:
            logger.info("Latest artifact already deployed, nothing to do")

    except Exception as e:
        logger.critical(e, exc_info=True)


