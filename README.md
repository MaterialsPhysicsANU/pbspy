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

Run `pbspy-server` somewhere with SSH access to the supercomputer (see [docker-compose.yml](./docker-compose.yml)
for a containerised example), then connect to it with `ServerBackend`:

```python
from pbspy import Job, JobDescription, ServerBackend

backend = ServerBackend(
    "pbspy-server.example.com", api_key="..."
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

By default `pbspy-server` runs every PBS command (`qsub`, `qstat`, file reads) over a fresh SSH
connection to the supercomputer (`--ssh-host gadi.nci.org.au`). `ServerBackend` doesn't know or
care which of the deployments below is on the other end — the wire protocol is identical either way.

### Running the server on the supercomputer itself (persistent sessions)

If your supercomputer supports long-running background processes (e.g. NCI Gadi's
[persistent sessions](https://opus.nci.org.au/display/Help/Persistent+Sessions)), you can instead
run `pbspy-server` directly there — PBS commands then run in-process with no per-command SSH
round trip:

```bash
persistent-sessions start pbspy
ssh pbspy.<user>.<project>.ps.gadi.nci.org.au
uv tool install pbspy
pbspy-server --host 127.0.0.1   # no --ssh-host: PBS commands run locally
```

Persistent-session hostnames are only resolvable from inside the supercomputer's network, so a
client outside it can't connect directly. Run a `ProxyServer` wherever your existing
`ServerBackend`-based code already points (e.g. in place of the direct-SSH daemon above) — it
relays each connection to the real server via `ssh -W`, so existing client code needs no changes at
all:

```bash
pbspy-server --proxy-to pbspy.<user>.<project>.ps.gadi.nci.org.au --remote-port 9876
```

(Add `ProxyJump`/`-J` to your SSH config for that host alias first, since the persistent-session
hostname needs to be reached via a login node.)

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
