"""Runtime execution layer.

Responsibilities are separated on purpose:

* ``contracts`` - the plans/handles exchanged between components;
* ``docker_backend`` - the authorized runtime interface (containers);
* ``supervisor`` - worker lifecycle, including termination;
* ``execution`` - task submission and execution-identity tracking;
* ``injectors`` - one mechanism per failure scenario;
* ``fault_controller`` - resolves/activates injectors and records evidence;
* ``observer`` / ``evaluator`` - evidence collection and the verdict;
* ``finalizer`` - idempotent cleanup;
* ``orchestrator`` - coordinates the above and owns the lifecycle.

The SDK never receives runtime authority: only this package talks to Docker.
"""
