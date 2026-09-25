"""Compatibility entry point for building the Pulsar UI."""

from pulsar.components import PulsarUI


__all__ = ["PulsarUI", "build_ui"]


def build_ui(server, refresh_variable_list=None, campaign_name=""):
    # Kept for compatibility with the original top-level application API.
    _ = refresh_variable_list
    return PulsarUI(server, campaign_name=campaign_name)
