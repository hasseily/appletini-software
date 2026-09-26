# Appletini port assessments

- Always evaluate TURBO mode when assessing game ports or graphics performance.
  TURBO batches video writes; do not model each write as a synchronous 1 MHz
  motherboard bus transaction or use that model to rule out a port.
- Base performance estimates on TURBO's actual batching, synchronization and
  I/O behaviour. If a local checkout or older document describes a different
  implementation, identify the version mismatch and verify the target before
  drawing a bandwidth conclusion.
