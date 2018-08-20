
# A very simple Flask Hello World app for you to get started with...

from flask import Flask

from flask import request
import json, re, os, shutil, urllib

from github import Github
from travispy import TravisPy

import warnings

from settings import *

RAW_GITHUB_LINK_TEMPLATE = 'https://raw.githubusercontent.com/{user}/{repo_name}/{branch}/{path}'

github = Github(GITHUB_USER, GITHUB_TOKEN)
travis = TravisPy.github_auth(GITHUB_TOKEN)

app = Flask(__name__)

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

def create_reseved_comment_for_pr(github_pr):
    return github_pr.create_issue_comment('Reserved for artifacts. Sorry :P')

def find_or_create_bot_pr_comment(github_pr):
    comments = github_pr.get_issue_comments()

    for comment in comments:
        if comment.user.login == GITHUB_USER:
            return comment

    # No comment, create one
    return create_reseved_comment_for_pr(github_pr)

def generate_comment_from_platforms_and_links(platforms_and_links):
    comment = BOT_COMMENT_BODY_TEMPLATE

    for platform, link in platforms_and_links:
        comment += BOT_COMMENT_DOWNLOAD_LINE_TEMPLATE.format(platform=platform, link=link)

    comment += BOT_COMMENT_FOOTER

    return comment

def update_comment(github_pr, artifacts_name_and_links):
    bot_comment = find_or_create_bot_pr_comment(github_pr)
    new_body = generate_comment_from_platforms_and_links(artifacts_name_and_links)

    bot_comment.edit(new_body)

def upload_artifacts_to_github_repo(repo, git_dir, atrifacts_content_and_path):
    for path, content in atrifacts_content_and_path:
    
        path = str("/" + git_dir + "/" + path)
    
        warnings.warn(path)
        repo.create_file(
            path, # path
            "Automaticlly upload a new file", # commit message
            content, # content
            GITHUB_OBJECTS_REPO_BRANCH # Branch 
        )

        yield RAW_GITHUB_LINK_TEMPLATE.format(
                user=GITHUB_USER,
                repo_name=GITHUB_OBJECTS_REPO,
                branch=GITHUB_OBJECTS_REPO_BRANCH,
                path=path)


def get_artifact_link_from_job(job):
    raw_log = job.log.body
    result = re.findall('(https://transfer\.sh/\S+)', raw_log)
    if not result:
        return ''

    link = result[0]

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
    warnings.warn(str(dir(travis_build)))
    warnings.warn(str(travis_build.pull_request))
    pull = repo.get_pull(travis_build.pull_request_number)

    return pull
    
def download_link(link):
    response = urllib.request.urlopen(link)
    return response.read()

def get_links_contents_and_paths(links):
    for link in links:
        # That way we only have one binary on ram each time. 
        # (as long as we never store the result in a list)
        yield (link.split('/')[-1], download_link(link))

@app.route('/', methods=['POST'])
def main():
    json_data = json.loads(request.data.decode('utf-8'))

    # Make sure we have the artifacts.
    if json_data.get('state', '') == 'success':

        travis_url = json_data['target_url']
        build = travis_url_to_build(travis_url)
        repo = github.get_repo(json_data['repository']['full_name'])
       
        if build.pull_request == False:
            return "Not a PR"

        # Retrive the download links
        links = get_artifact_links_from_build(build)
        if not links:
            return "No links found"
        
        # Retrive pull request
        pull_request = get_pull_request_from_build(repo, build)

        # Download the download links to a variable 
        links_content_and_paths = get_links_contents_and_paths(links)
        
        # Upload them to our repo.
        upload_repo = github.get_repo(github.get_user().login + "/" + GITHUB_OBJECTS_REPO)
        github_download_links = upload_artifacts_to_github_repo (upload_repo, json_data['sha'], links_content_and_paths)

        # Resolve platform name for each link. 
        links_platforms = (platform_from_link(link) for link in github_download_links)

        # Update our comment, or create a new one.
        update_comment(pull_request, zip(links_platforms, github_download_links))
        return "Done;"
    else:
        return "state != success"

