import typer
from rich import print

from pbspy import Job, JobDescription, QueueLimits


def main() -> None:
    # Run a job with some explicit parameters
    job_a = (
        JobDescription(
            name="job_a",
            ncpus=4,
            mem="1GB",
            walltime="00:05:00",
        )
        .add_command(["echo", "A"])
        .submit()
    )

    # Submit another job that waits for job_a to finish
    # This job uses all available resources (cpus, mem, jobfs) of a single node
    queue_limits = QueueLimits(cpus_per_node=48, max_mem_per_node=190, max_jobfs_per_node=400)
    job_b = (
        JobDescription.from_nodes(
            name="job_b",
            nnodes=1,
            queue="normal",
            queue_limits=queue_limits,
            walltime="00:05:00",
            afterok=[job_a],
        )
        .add_command(["echo", "B"])
        .submit()
    )

    # Get the result of the jobs
    # result_a = job_a.result() # wait for job_a to finish and get result
    (result_a, result_b) = Job.result_all([job_a, job_b])  # wait for job_a and job_b to finish and get results
    print("job_a:", result_a.output.strip())
    print("job_b:", result_b.output.strip())


if __name__ == "__main__":
    typer.run(main)
