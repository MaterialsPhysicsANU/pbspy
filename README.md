# pbspy

[![PyPI - Version](https://img.shields.io/pypi/v/pbspy)](https://pypi.org/project/pbspy/)
[![docs](https://img.shields.io/pypi/v/pbspy?label=docs&color=blue)](https://MaterialsPhysicsANU.github.io/pbspy/)
![Python Version](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2FMaterialsPhysicsANU%2Fpbspy%2Fmain%2Fpyproject.toml)
![PyPI - License](https://img.shields.io/pypi/l/pbspy)
[![build](https://github.com/MaterialsPhysicsANU/pbspy/actions/workflows/main.yml/badge.svg)](https://github.com/MaterialsPhysicsANU/pbspy/actions/workflows/main.yml)

A python package for working with the Portable Batch System (PBS) job scheduler.

See the [documentation](https://MaterialsPhysicsANU.github.io/pbspy/) for more information.

## Example

### Running directly on a supercomputer login-node

```python
from pbspy import Job, JobDescription

# Run a job with some explicit parameters
job_a = (
    JobDescription(name="job_a", ncpus=4, mem="192GB", walltime="00:05:00")
    .add_command(["echo", "A"])
    .submit()
)

# Submit another job that waits for job_a to finish
job_b = (
    JobDescription(name="job_b", ncpus=1, walltime="00:05:00", afterok=[job_a])
    .add_command(["echo", "B"])
    .submit()
)

# Get the result of the jobs
# result_a = job_a.result() # wait for job_a to finish and get result
(result_a, result_b) = Job.result_all(
    [job_a, job_b]
)  # wait for job_a and job_b to finish and get results
print("job_a:", result_a.output.strip())
print("job_b:", result_b.output.strip())
```

### Submitting from a remote machine via a `pbspy-server` daemon

`pbspy-server` runs every PBS command (`qsub`, `qstat`, `qdel`, file reads) locally,
so it must run somewhere with direct PBS access. On NCI Gadi that means a
[persistent session](https://opus.nci.org.au/display/Help/Persistent+Sessions):

```bash
persistent-sessions start pbspy
ssh pbspy.<user>.<project>.ps.gadi.nci.org.au
uv tool install pbspy
pbspy-server --host 0.0.0.0 --api-key ...
```

Then connect to it with `ServerBackend` (from inside the supercomputer's network, or via an SSH
tunnel/port-forward if you need to reach it from elsewhere):

```python
from pbspy import Job, JobDescription, ServerBackend

backend = ServerBackend(
    "pbspy.<user>.<project>.ps.gadi.nci.org.au", api_key="..."
)  # api_key only if the server requires it

job_a = (
    JobDescription(name="job_a", ncpus=4, mem="192GB", walltime="00:05:00")
    .add_command(["echo", "A"])
    .submit(backend=backend)
)

job_b = (
    JobDescription(name="job_b", ncpus=1, walltime="00:05:00", afterok=[job_a])
    .add_command(["echo", "B"])
    .submit(backend=backend)
)

(result_a, result_b) = Job.result_all([job_a, job_b])
print("job_a:", result_a.output.strip())
print("job_b:", result_b.output.strip())
```

## Output (partially executed)

```text
✓ 124397435.gadi-pbs job_a
0:01:15 124397436.gadi-pbs job_b
```

## Output (completed)

```text
✓ 124397435.gadi-pbs job_a
✓ 124397436.gadi-pbs job_b

job_a: A
job_b: B
```

## License

`pbspy` is licensed under the MIT License [LICENSE](./LICENSE) or <http://opensource.org/licenses/MIT>.
