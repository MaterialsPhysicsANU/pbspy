from pbspy import JobDescription


def test_default() -> None:
    job_description = (
        JobDescription()
        .add_command(["echo", "a"])
        .add_command(["echo", "b"])
        .add_command(["echo", "c"])
        .add_command(["echo", "d"])
        .add_command(["echo", "e"])
    )
    print(job_description.script())
    result = job_description.submit().result()
    assert result.exit_code == 0
    assert result.output == "a\nb\nc\nd\ne\n"
    # assert result.error == ""
