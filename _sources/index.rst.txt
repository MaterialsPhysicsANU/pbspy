
pbspy
=====================================

.. image:: https://img.shields.io/pypi/v/pbspy
   :alt: PyPI - Version
   :target: https://pypi.org/project/pbspy/

.. image:: https://img.shields.io/pypi/v/pbspy?label=docs&color=blue&link=https%3A%2F%2FMaterialsPhysicsANU.github.io%2Fpbspy%2F
   :alt: docs
   :target: https://MaterialsPhysicsANU.github.io/pbspy/

.. image:: https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2FMaterialsPhysicsANU%2Fpbspy%2Fmain%2Fpyproject.toml
   :alt: Python Version

.. image:: https://img.shields.io/pypi/l/pbspy
   :alt: PyPI - License

.. image:: https://github.com/MaterialsPhysicsANU/pbspy/actions/workflows/main.yml/badge.svg
   :alt: build
   :target: https://github.com/MaterialsPhysicsANU/pbspy/actions/workflows/main.yml

A python package for working with the Portable Batch System (PBS) job scheduler.

.. autodoc2-summary::
    pbspy
    pbspy.gadi

Usage
-----

Submitting a Job
~~~~~~~~~~~~~~~~

To submit a job to the PBS scheduler, create a :py:class:`~pbspy.JobDescription` and :py:meth:`~pbspy.JobDescription.submit()` it:

.. code-block:: python

    from pbspy import Job, JobDescription

    job_description = (
        JobDescription(
            name="job_tiny",
            queue="normal",
            ncpus=1,
            mem="100MB",
            jobfs="0MB",
            walltime="00:05:00",
        )
        .add_command(["echo", "A"])
        .add_command(["echo", "B"])
    )
    job: Job = job_description.submit()
    print(job.job_id)

The :class:`~pbspy.Job` holds a ``job_id`` and other attributes.

The :py:meth:`~pbspy.JobDescription.from_nodes()` constructor of :py:class:`~pbspy.JobDescription` creates a job description that uses all available resources for some number of nodes.
Resource limits for a queue must be provided in a :class:`~pbspy.QueueLimits`.

.. code-block:: python

    from pbspy import Job, JobDescription

    queue_limits = QueueLimits(
        cpus_per_node=48, max_mem_per_node=190, max_jobfs_per_node=400
    )
    job_description = JobDescription.from_nodes(
        nnodes=2,
        name="job_1node",
        queue="normal",
        queue_limits=queue_limits,
        walltime="00:05:00",
    )

:py:mod:`pbspy` does not currently support querying the :class:`~pbspy.QueueLimits` of a PBS queue.
Note that some PBS systems do not make such information queryable anyway.

The :py:mod:`pbspy.gadi` submodule has pre-defined :class:`~pbspy.QueueLimits` for the Gadi supercomputer.

.. note::
    Contributions are welcomed for :class:`~pbspy.QueueLimits` for other clusters.

Retrieving Job Output
~~~~~~~~~~~~~~~~~~~~~

The output of a job can be retrieved by calling :py:meth:`~pbspy.Job.result()` on a :class:`~pbspy.Job`:

.. code-block:: python

    result: JobResult = job.result()
    print(result.output)

:py:meth:`~pbspy.Job.result()` waits for the job to complete before returning a :class:`~pbspy.JobResult` that holds the ``stdout``, ``stderr``, ``exit_code``, and other information output by PBS.

Wait for multiple jobs to complete with the :py:meth:`~pbspy.Job.result_all()` static method of :class:`~pbspy.Job`.


License
-----------------

``pbspy`` is licensed under the MIT License <http://opensource.org/licenses/MIT>.


API Documentation
-----------------

.. toctree::
   apidocs/index
