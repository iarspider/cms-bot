import importlib
import json
import os
import sys
import traceback

import github
import pytest

from . import Framework
from .Framework import readLine

actions = []

################################################################################
# Hook some PyGithub methods to log them

github__issuecomment__edit = github.IssueComment.IssueComment.edit


def comment__edit(self, body):
    actions.append({"type": "edit-comment", "data": body})
    print("DRY RUN: Updating existing comment with text")
    print(body.encode("ascii", "ignore").decode())


github.IssueComment.IssueComment.edit = comment__edit

################################################################################

github__issuecomment__delete = github.IssueComment.IssueComment.delete


def comment__delete(self):
    actions.append({"type": "delete-comment", "data": str(self)})
    return


github.IssueComment.IssueComment.delete = comment__delete

################################################################################
github__issue__create_comment = github.Issue.Issue.create_comment


def issue__create_comment(self, body):
    actions.append({"type": "create-comment", "data": body})
    print("DRY RUN: Creating comment with text")
    print(body.encode("ascii", "ignore").decode())


github.Issue.Issue.create_comment = issue__create_comment

################################################################################
github__issue__edit = github.Issue.Issue.edit


# noinspection PyUnusedLocal
def issue__edit(
    self,
    title=github.GithubObject.NotSet,
    body=github.GithubObject.NotSet,
    assignee=github.GithubObject.NotSet,
    state=github.GithubObject.NotSet,
    milestone=github.GithubObject.NotSet,
    labels=github.GithubObject.NotSet,
    assignees=github.GithubObject.NotSet,
):

    if milestone != github.GithubObject.NotSet:
        actions.append(
            {"type": "update-milestone", "data": {"id": milestone.id, "title": milestone.title}}
        )

    if state == "closed":
        actions.append({"type": "close", "data": None})

    if state == "open":
        actions.append({"type": "open", "data": None})


github.Issue.Issue.edit = issue__edit
################################################################################
github__commit__create_status = github.Commit.Commit.create_status


def commit__create_status(self, state, target_url=None, description=None, context=None):
    actions.append(
        {
            "type": "status",
            "data": {
                "commit": self.sha,
                "state": state,
                "target_url": target_url,
                "description": description,
                "context": context,
            },
        }
    )

    if target_url is None:
        target_url = github.GithubObject.NotSet

    if description is None:
        description = github.GithubObject.NotSet

    if context is None:
        context = github.GithubObject.NotSet
    print(
        "DRY RUN: set commit status state={0}, target_url={1}, description={2}, context={3}".format(
            state, target_url, description, context
        )
    )


github.Commit.Commit.create_status = commit__create_status

################################################################################
# TODO: remove once we update pygithub
# Taken from: https://github.com/PyGithub/PyGithub/pull/2939/files


# noinspection PyProtectedMember
def get_commit_files(commit):
    return github.PaginatedList.PaginatedList(
        github.File.File,
        commit._requester,
        commit.url,
        {},
        None,
        "files",
    )


# noinspection PyUnusedLocal
def get_commit_files_pygithub(repo, commit):
    return (x.filename for x in get_commit_files(commit))


################################################################################
process_pr__read_bot_cache = None


# noinspection PyCallingNonCallable
def read_bot_cache(data):
    res = process_pr__read_bot_cache(data)
    actions.append({"type": "load-bot-cache", "data": res})


################################################################################
process_pr__create_property_file = None


# noinspection PyCallingNonCallable
def create_property_file(out_file_name, parameters, dryRun):
    actions.append(
        {"type": "create-property-file", "data": {"filename": out_file_name, "data": parameters}}
    )

    process_pr__create_property_file(out_file_name, parameters, True)


################################################################################

process_pr__set_comment_emoji_cache = None


# noinspection PyCallingNonCallable
def set_comment_emoji_cache(dryRun, bot_cache, comment, repository, emoji="+1", reset_other=True):
    actions.append({"type": "emoji", "data": (comment.id, emoji, reset_other)})
    process_pr__set_comment_emoji_cache(
        True, bot_cache, comment, repository, emoji="+1", reset_other=True
    )


################################################################################
process_pr__on_labels_changed = None


def on_labels_changed(added_labels, removed_labels):
    actions.append(
        {
            "type": "add-label",
            "data": sorted(
                list(
                    added_labels,
                )
            ),
        }
    )
    actions.append({"type": "remove-label", "data": sorted(list(removed_labels))})


################################################################################
class TestProcessPr(Framework.TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.process_pr_module = None
        self.prId = -1

    @staticmethod
    def compareActions(res_, expected_):
        res = {json.dumps(x, sort_keys=True) for x in res_}
        expected = {json.dumps(x, sort_keys=True) for x in expected_}

        if res.symmetric_difference(expected):
            for itm in res - expected:
                print("New action", itm)

            for itm in expected - res:
                print("Missing action", itm)

            pytest.fail("Actions mismatch")

    def __openEventFile(self, mode):
        fileName = ""
        for _, _, functionName, _ in traceback.extract_stack():
            if (
                functionName.startswith("test")
                # or functionName == "setUp"
                # or functionName == "tearDown"
            ):
                if (
                    functionName != "test"
                ):  # because in class Hook(Framework.TestCase), method testTest calls Hook.test
                    fileName = os.path.join(
                        os.path.dirname(__file__),
                        self.actionDataFolder,
                        f"{self.__class__.__name__}.{functionName}.json",
                    )
        if not fileName:
            raise RuntimeError("Could not determine event file name!")

        if fileName != self.__eventFileName:
            self.__closeEventReplayFileIfNeeded()
            self.__eventFileName = fileName
            self.__eventFile = open(self.__eventFileName, mode, encoding="utf-8")
        return self.__eventFile

    def __closeEventReplayFileIfNeeded(self):
        if self.__eventFile is not None:
            if (
                not self.recordMode
            ):  # pragma no branch (Branch useful only when recording new tests, not used during automated tests)
                self.assertEqual(readLine(self.__eventFile), "")
            self.__eventFile.close()

    def setUp(self):
        global process_pr__read_bot_cache, process_pr__set_comment_emoji_cache, process_pr__create_property_file, process_pr__on_labels_changed
        super().setUp()

        self.__eventFileName = ""
        self.__eventFile = None

        self.actionDataFolder = "PRActionData"
        if not os.path.exists(self.actionDataFolder):
            os.mkdir(self.actionDataFolder)

        repo_config_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "repos", "iarspider_cmssw", "cmssw")
        )
        assert os.path.exists(repo_config_dir)
        assert os.path.exists(os.path.join(repo_config_dir, "repo_config.py"))
        sys.path.insert(0, repo_config_dir)

        if "repo_config" in sys.modules:
            importlib.reload(sys.modules["repo_config"])
            importlib.reload(sys.modules["milestones"])
            importlib.reload(sys.modules["releases"])
            importlib.reload(sys.modules["categories"])
        else:
            importlib.import_module("repo_config")

        self.repo_config = sys.modules["repo_config"]
        assert "iarspider_cmssw" in self.repo_config.__file__

        if not self.process_pr_module:
            self.process_pr_module = importlib.import_module("process_pr")
            self.process_pr = self.process_pr_module.process_pr
            # TODO: remove once we update pygithub
            self.process_pr_module.get_commit_files = get_commit_files_pygithub

            # Replace some methods to log performed actions
            process_pr__read_bot_cache = self.process_pr_module.read_bot_cache
            self.process_pr_module.read_bot_cache = read_bot_cache

            process_pr__set_comment_emoji_cache = self.process_pr_module.set_comment_emoji_cache
            self.process_pr_module.set_comment_emoji_cache = set_comment_emoji_cache

            process_pr__create_property_file = self.process_pr_module.create_property_file
            self.process_pr.create_property_file = create_property_file

            process_pr__on_labels_changed = self.process_pr_module.on_labels_changed
            self.process_pr_module.on_labels_changed = on_labels_changed

            process_pr__set_comment_emoji_cache = self.process_pr_module.set_comment_emoji_cache
            self.process_pr_module.set_comment_emoji_cache = process_pr__set_comment_emoji_cache

    def runTest(self, prId=17):
        repo = self.g.get_repo("iarspider-cmssw/cmssw")
        issue = repo.get_issue(prId)

        if self.recordMode:
            self.__openEventFile("w")
            self.replayData = None
        else:
            f = self.__openEventFile("r")
            self.replayData = json.load(f)

        self.process_pr(
            self.repo_config,
            self.g,
            repo,
            issue,
            False,
            self.repo_config.CMSBUILD_USER,
        )
        self.processPrData = actions
        self.checkOrSaveTest()
        self.__closeEventReplayFileIfNeeded()

    def checkOrSaveTest(self):
        if self.recordMode:
            json.dump(self.processPrData, self.__eventFile, indent=4)
        else:
            TestProcessPr.compareActions(self.processPrData, self.replayData)

    def mark_tests(
        self,
        dryRun,
        arch="el8_amd64_gcc12",
        queue="_X",
        required=True,
        unittest=True,
        addon=True,
        relvals=True,
        input_=True,
        comparision=True,
    ):
        repo = self.g.get_repo("iarspider-cmssw/cmssw")
        pr = repo.get_pull(self.prId)
        commit = pr.get_commits().reversed[0]
        prefix = "cms/" + str(self.prId) + "/"
        if queue.endswith("_X"):
            queue = queue.rstrip("_X")
        prefix += (queue + "/" if queue else "") + arch
        if not dryRun:
            commit.create_status(
                "success" if all((unittest, addon, relvals, input_, comparision)) else "error",
                "https://cmssdt.cern.ch/jenkins/job/ib-run-pr-tests/38669/",
                context="{0}".format(prefix, "required" if required else "optional"),
            )
            commit.create_status(
                "success",
                "https://cmssdt.cern.ch/jenkins/job/ib-run-pr-tests/38669/",
                context="{0}/{1}".format(prefix, "required" if required else "optional"),
                description="Finished",
            )
            commit.create_status(
                "success" if unittest else "error",
                "https://cmssdt.cern.ch/jenkins/job/ib-run-pr-tests/38669/",
                context="{0}/unittest".format(prefix),
            )
            commit.create_status(
                "success" if addon else "error",
                "https://cmssdt.cern.ch/jenkins/job/ib-run-pr-addon/22833/",
                context="{0}/addon".format(prefix),
            )
            commit.create_status(
                "success" if relvals else "error",
                "https://cmssdt.cern.ch/jenkins/job/ib-run-pr-relvals/43002/",
                context="{0}/relvals".format(prefix),
            )
            commit.create_status(
                "success" if input_ else "error",
                "https://cmssdt.cern.ch/jenkins/job/ib-run-pr-relvals/43000/",
                context="{0}/relvals/input".format(prefix),
            )
            commit.create_status(
                "success" if comparision else "error",
                "https://cmssdt.cern.ch/jenkins/job/compare-root-files-short-matrix/62168/",
                context="{0}/comparision".format(prefix),
            )

    def test_new_pr(self):
        self.runTest()

    def test_code_check_approved(self):
        self.runTest()

    def test_sign_core(self):
        self.runTest()

    def test_partial_reset(self):
        self.runTest()

    def test_reset_signature(self):
        self.runTest()

    def test_revert(self):
        self.runTest()

    def test_start_tests(self):
        self.runTest()

    # # Dummy test
    # def test_mark_rejected(self):
    #     self.mark_tests(False, unittest=False)
    #
    # def test_mark_passed(self):
    #     self.mark_tests(False)

    def test_tests_rejected(self):
        self.runTest()

    def test_tests_passed(self):
        self.runTest()

    def test_hold(self):
        self.runTest()

    def test_unhold(self):
        self.runTest()

    def test_assign(self):
        self.runTest()

    def test_unassign(self):
        self.runTest()

    def test_test_params(self):
        self.runTest()

    def test_run_test_params(self):
        self.runTest()

    def test_abort(self):
        self.runTest()

    def test_close(self):
        self.runTest()

    def test_reopen(self):
        self.runTest()

    def test_invalid_type(self):
        self.runTest()

    def test_valid_type(self):
        self.runTest()

    def test_clean_squash(self):
        self.runTest()

    def test_dirty_squash(self):
        self.runTest()

    def test_sign_reject(self):
        self.runTest()

    def test_many_commits_warn(self):
        self.runTest(18)

    def test_many_commits_ok(self):
        self.runTest(18)

    def test_too_many_commits(self):
        self.runTest(18)

    # Not yet implemented
    # def test_future_commit(self):
    #     self.runTest()

    # Not yet implemented
    # def test_backdated_commit(self):
    #     self.runTest()
