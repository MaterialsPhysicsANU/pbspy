:py:mod:`pbspy`
===============

.. py:module:: pbspy

.. autodoc2-docstring:: pbspy
   :allowtitles:

Submodules
----------

.. toctree::
   :titlesonly:
   :maxdepth: 1

   pbspy.gadi

Package Contents
----------------

Classes
~~~~~~~

.. list-table::
   :class: autosummary longtable
   :align: left

   * - :py:obj:`JobDescription <pbspy.JobDescription>`
     - .. autodoc2-docstring:: pbspy.JobDescription
          :summary:
   * - :py:obj:`Job <pbspy.Job>`
     - .. autodoc2-docstring:: pbspy.Job
          :summary:
   * - :py:obj:`JobResult <pbspy.JobResult>`
     - .. autodoc2-docstring:: pbspy.JobResult
          :summary:
   * - :py:obj:`QueueLimits <pbspy.QueueLimits>`
     - .. autodoc2-docstring:: pbspy.QueueLimits
          :summary:

Data
~~~~

.. list-table::
   :class: autosummary longtable
   :align: left

   * - :py:obj:`QueueLimitsMap <pbspy.QueueLimitsMap>`
     - .. autodoc2-docstring:: pbspy.QueueLimitsMap
          :summary:

API
~~~

.. py:class:: JobDescription
   :canonical: pbspy.JobDescription

   .. autodoc2-docstring:: pbspy.JobDescription

   .. py:attribute:: name
      :canonical: pbspy.JobDescription.name
      :type: str | None
      :value: None

      .. autodoc2-docstring:: pbspy.JobDescription.name

   .. py:attribute:: description
      :canonical: pbspy.JobDescription.description
      :type: str | None
      :value: None

      .. autodoc2-docstring:: pbspy.JobDescription.description

   .. py:attribute:: commands
      :canonical: pbspy.JobDescription.commands
      :type: list[str | list[str]]
      :value: 'field(...)'

      .. autodoc2-docstring:: pbspy.JobDescription.commands

   .. py:attribute:: queue
      :canonical: pbspy.JobDescription.queue
      :type: str | None
      :value: None

      .. autodoc2-docstring:: pbspy.JobDescription.queue

   .. py:attribute:: ncpus
      :canonical: pbspy.JobDescription.ncpus
      :type: int | None
      :value: None

      .. autodoc2-docstring:: pbspy.JobDescription.ncpus

   .. py:attribute:: mem
      :canonical: pbspy.JobDescription.mem
      :type: str | None
      :value: None

      .. autodoc2-docstring:: pbspy.JobDescription.mem

   .. py:attribute:: jobfs
      :canonical: pbspy.JobDescription.jobfs
      :type: str | None
      :value: None

      .. autodoc2-docstring:: pbspy.JobDescription.jobfs

   .. py:attribute:: walltime
      :canonical: pbspy.JobDescription.walltime
      :type: str | None
      :value: None

      .. autodoc2-docstring:: pbspy.JobDescription.walltime

   .. py:attribute:: storage
      :canonical: pbspy.JobDescription.storage
      :type: str | None
      :value: None

      .. autodoc2-docstring:: pbspy.JobDescription.storage

   .. py:attribute:: wd
      :canonical: pbspy.JobDescription.wd
      :type: bool
      :value: True

      .. autodoc2-docstring:: pbspy.JobDescription.wd

   .. py:attribute:: afterok
      :canonical: pbspy.JobDescription.afterok
      :type: list[pbspy.Job]
      :value: 'field(...)'

      .. autodoc2-docstring:: pbspy.JobDescription.afterok

   .. py:method:: from_nodes(nnodes: int, queue: str, queue_limits: pbspy.QueueLimits, **kwargs: typing.Any) -> pbspy.JobDescription
      :canonical: pbspy.JobDescription.from_nodes
      :classmethod:

      .. autodoc2-docstring:: pbspy.JobDescription.from_nodes

   .. py:method:: add_command(command: str | list[str]) -> typing.Self
      :canonical: pbspy.JobDescription.add_command

      .. autodoc2-docstring:: pbspy.JobDescription.add_command

   .. py:method:: script() -> str
      :canonical: pbspy.JobDescription.script

      .. autodoc2-docstring:: pbspy.JobDescription.script

   .. py:method:: submit() -> pbspy.Job
      :canonical: pbspy.JobDescription.submit

      .. autodoc2-docstring:: pbspy.JobDescription.submit

.. py:class:: Job
   :canonical: pbspy.Job

   .. autodoc2-docstring:: pbspy.Job

   .. py:attribute:: job_name
      :canonical: pbspy.Job.job_name
      :type: str | None
      :value: None

      .. autodoc2-docstring:: pbspy.Job.job_name

   .. py:attribute:: job_id
      :canonical: pbspy.Job.job_id
      :type: str
      :value: None

      .. autodoc2-docstring:: pbspy.Job.job_id

   .. py:attribute:: description
      :canonical: pbspy.Job.description
      :type: str | None
      :value: None

      .. autodoc2-docstring:: pbspy.Job.description

   .. py:method:: wait() -> None
      :canonical: pbspy.Job.wait

      .. autodoc2-docstring:: pbspy.Job.wait

   .. py:method:: _result_no_wait() -> pbspy.JobResult
      :canonical: pbspy.Job._result_no_wait

      .. autodoc2-docstring:: pbspy.Job._result_no_wait

   .. py:method:: result() -> pbspy.JobResult
      :canonical: pbspy.Job.result

      .. autodoc2-docstring:: pbspy.Job.result

   .. py:method:: wait_all(jobs: list[pbspy.Job]) -> None
      :canonical: pbspy.Job.wait_all
      :staticmethod:

      .. autodoc2-docstring:: pbspy.Job.wait_all

   .. py:method:: result_all(jobs: list[pbspy.Job]) -> list[pbspy.JobResult]
      :canonical: pbspy.Job.result_all
      :staticmethod:

      .. autodoc2-docstring:: pbspy.Job.result_all

.. py:class:: JobResult
   :canonical: pbspy.JobResult

   .. autodoc2-docstring:: pbspy.JobResult

   .. py:attribute:: exit_code
      :canonical: pbspy.JobResult.exit_code
      :type: int | None
      :value: None

      .. autodoc2-docstring:: pbspy.JobResult.exit_code

   .. py:attribute:: output
      :canonical: pbspy.JobResult.output
      :type: str
      :value: <Multiline-String>

      .. autodoc2-docstring:: pbspy.JobResult.output

   .. py:attribute:: error
      :canonical: pbspy.JobResult.error
      :type: str
      :value: <Multiline-String>

      .. autodoc2-docstring:: pbspy.JobResult.error

   .. py:attribute:: stats
      :canonical: pbspy.JobResult.stats
      :type: dict[str, str] | None
      :value: None

      .. autodoc2-docstring:: pbspy.JobResult.stats

.. py:class:: QueueLimits
   :canonical: pbspy.QueueLimits

   .. autodoc2-docstring:: pbspy.QueueLimits

   .. py:attribute:: cpus_per_node
      :canonical: pbspy.QueueLimits.cpus_per_node
      :type: int
      :value: None

      .. autodoc2-docstring:: pbspy.QueueLimits.cpus_per_node

   .. py:attribute:: max_mem_per_node
      :canonical: pbspy.QueueLimits.max_mem_per_node
      :type: int
      :value: None

      .. autodoc2-docstring:: pbspy.QueueLimits.max_mem_per_node

   .. py:attribute:: max_jobfs_per_node
      :canonical: pbspy.QueueLimits.max_jobfs_per_node
      :type: int
      :value: None

      .. autodoc2-docstring:: pbspy.QueueLimits.max_jobfs_per_node

.. py:data:: QueueLimitsMap
   :canonical: pbspy.QueueLimitsMap
   :type: typing.TypeAlias
   :value: None

   .. autodoc2-docstring:: pbspy.QueueLimitsMap
