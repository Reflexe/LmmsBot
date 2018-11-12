from flask import Flask

from flask import request
import json, re, os, shutil

from urllib.request import urlretrieve

from github import Github
from travispy import TravisPy

from settings import *

import logging

github = Github(GITHUB_USER, GITHUB_TOKEN)
travis = TravisPy.github_auth(GITHUB_TOKEN)

app = Flask(__name__)

from git import Repo

_link_extension_to_platform_title = {
    'dmg': "Mac",
    'AppImage': "Linux",
    'win32.exe': "Windows 32 Bit",
    'win64.exe': "Windows 64 Bit",
}

def platform_from_link(link):
    for extension, title in _link_extension_to_platform_title.items():
        if link.endswith(extension):
            return title

    return "Undefined Platform"

def build_id_from_travis_url(url):
    return re.findall('http[s]?://travis-ci\.(?:org|com)/(?:\w+)/(?:\w+)/builds/([0-9]+)(?:.*)', url)[0]

def is_travis_url(url):
    return "travis-ci" in url

def create_reseved_comment_for_pr(github_pr, initial_content):
    return github_pr.create_issue_comment(initial_content)

def find_or_create_bot_pr_comment(github_pr, initial_content):
    '''
        Find our comment or create it if it does not exist.

        Returns a pair:
            first:  <boolean>   Have we created a new comment?
            second: <comment>   The comment object.
    '''

    comments = list(github_pr.get_issue_comments())

    for comment in comments:
        if comment.user.login == GITHUB_USER:
            return (False, comment)

    # No comment, create one
    return (True, create_comment_for_pr(github_pr, initial_content))

def generate_comment_from_platforms_and_links(platforms_and_links):
    platforms_and_links = list(platforms_and_links)

    comment = BOT_COMMENT_BODY_TEMPLATE

    for platform, link in platforms_and_links:
        comment += BOT_COMMENT_DOWNLOAD_LINE_TEMPLATE.format(platform=platform, link=link)

    comment += BOT_COMMENT_FOOTER

    return comment

def update_comment(github_pr, artifacts_name_and_links):
    new_body = generate_comment_from_platforms_and_links(artifacts_name_and_links)
    should_not_edit, bot_comment = find_or_create_bot_pr_comment(github_pr, new_body)

    if not should_not_edit:
        bot_comment.edit(new_body)

def upload_artifacts_to_github_repo(tag, artifacts_repo, artifact_paths):
    release = artifacts_repo.get_release(tag)

    # We already have this release tag, just remove it.
    if release is not None:
        release.delete_release()


    release = artifacts_repo.create_git_release(tag, "Name", "Message")


    for path in artifact_paths:
       asset = release.upload_asset(path)

       yield asset.browser_download_url



def get_artifact_link_from_job(job):
    raw_log = job.log.body
    result = re.findall('(https://transfer\.sh/\S+)travis_time', raw_log)
    if not result:
        return ''

    link = result[0]

    # Filter strage string after the link


    return link

def travis_url_to_build(travis_url):
    build_id = build_id_from_travis_url(travis_url)

    build = travis.build(int(build_id))

    return build

def get_artifact_links_from_build(travis_build):
    for job in travis_build.jobs:
        maybe_link = get_artifact_link_from_job(job)
        if maybe_link:
            yield maybe_link

def get_pull_request_from_build(repo, travis_build):
    pull = repo.get_pull(travis_build.pull_request_number)

    return pull


def download_link_to(link, path):
    '''Download @link to @path

    return downloaded path
    '''

    path = path + '/' + link.split('/')[-1]

    urlretrieve(link, path)

    return path

@app.route('/', methods=['POST'])
def main():
    json_data = json.loads(request.data.decode('utf-8'))

    if json_data.get('state', '') == 'success':
        os.makedirs(TEMP_DIR_PATH, exist_ok=True)
        os.chdir(TEMP_DIR_PATH)

        download_temp_dirname = json_data['sha']
        os.makedirs(download_temp_dirname, exist_ok=True)

        if not is_travis_url(json_data['target_url']):
            return "Not Travis"

        travis_url = json_data['target_url']
        build = travis_url_to_build(travis_url)
        build_id = build_id_from_travis_url(travis_url)
        repo = github.get_repo(json_data['repository']['full_name'])

        if build.pull_request == False:
            return "Not a PR"

        links = get_artifact_links_from_build(build)
        pull_request = get_pull_request_from_build(repo, build)

        downloaded_files = []
        for link in links:
            downloaded_file = download_link_to (link, download_temp_dirname)
            downloaded_files.append (downloaded_file)

        if not downloaded_files:
            return "No outputs."

        links_platforms = [platform_from_link(link) for link in downloaded_files]

        artifacts_repo = github.get_repo(GITHUB_USER + "/" + GITHUB_OBJECTS_REPO)

        # Remove one digit because github does not like 40 hex digits.
        release_tag = json_data['sha'][:-1]

        github_download_links = upload_artifacts_to_github_repo (release_tag, artifacts_repo, downloaded_files)
        github_download_links = list(github_download_links)

        update_comment(pull_request, zip(links_platforms, github_download_links))

        shutil.rmtree(TEMP_DIR_PATH + '/' + download_temp_dirname)
        return "Done;"
    else:
        return "state != success"

    return "Hi!"
