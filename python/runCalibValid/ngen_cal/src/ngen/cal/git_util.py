import configparser
import logging
import os

logger = logging.getLogger(__name__)

def print_git_info():
    """
    Reads git information from git_info.txt and logs it.
    """
    git_info = read_git_info()

    if not git_info:
        logger.warning("Failed to retrieve git information.")
        return

    # Log the retrieved git information
    logger.info(f"commit_hash: {git_info.get('commit_hash', 'N/A')}")
    logger.info(f"branch: {git_info.get('branch', 'N/A')}")
    tags = git_info.get('tags', '').strip()
    if tags:
        logger.info(f"tags: {tags}")
    logger.info(f"author: {git_info.get('author', 'N/A')}")
    logger.info(f"commit_date: {git_info.get('commit_date', 'N/A')}")
    logger.info(f"message: {git_info.get('message', 'N/A')}")
    logger.info(f"build_date: {git_info.get('build_date', 'N/A')}")


NGEN_CAL_REPO = '/ngen-app/ngen-cal'
def read_git_info():
    """
    Reads the git_info.properties file (formatted as an INI file with a [default] section)
    and returns its contents as a dictionary.
    """
    git_file_path = os.path.join(NGEN_CAL_REPO, "git_info.properties")
    config = configparser.ConfigParser()
    try:
        config.read(git_file_path)
        # Retrieve the [default] section as a dictionary.
        return dict(config["default"])
    except KeyError:
        logger.error(f"Section [default] not found in the file: {git_file_path}")
    except Exception as e:
        logger.exception(f"Error reading git info file: {e}")
    return {}

