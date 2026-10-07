"""负向控制：故意失败的用例，用于证明 required check 真的会拒绝错误 PR。

这个文件只在一次性的审计分支上存在，用来验证分支保护不是形同虚设；
它不会被合并进 main。
"""


def test_required_checks_must_reject_this_pr() -> None:
    assert False, "负向控制：这条断言必须失败，用于证明 CI 与 required check 会拦截错误 PR"
