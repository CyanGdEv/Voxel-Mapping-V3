"""Optional peak-memory telemetry; compilation never requires Unix resource APIs."""
import sys


def peak_process_rss_mib():
    try:
        import resource
    except ImportError:
        return None
    divisor = 1024 * 1024 if sys.platform == 'darwin' else 1024
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / divisor
