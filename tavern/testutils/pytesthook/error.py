import logging
import re
import io
import py
import yaml
from _pytest._code.code import FormattedExcinfo

from tavern.util import exceptions
from tavern.util.dict_util import format_keys

logger = logging.getLogger(__name__)


class ReprdError(object):
    def __init__(self, exce, item):
        self.exce = exce
        self.item = item

    def _get_available_format_keys(self):
        """Try to get the format variables for the stage

        If we can't get the variable for this specific stage, just return the
        global config which will at least have some format variables

        Returns:
            dict: variables for formatting test
        """
        try:
            # pylint: disable=protected-access
            keys = self.exce._excinfo[1].test_block_config["variables"]
        except AttributeError:
            logger.warning("Unable to read stage variables - error output may be wrong")
            keys = self.item.global_cfg

        return keys

    def _print_format_variables(self, tw, code_lines):
        """Print a list of the format variables and their value at this stage

        If the format variable is not defined, print it in red as '???'

        Args:
            tw (TerminalWriter): Pytest TW instance
            code_lines (list(str)): Source lines for this stage

        Returns:
            list(str): List of all missing format variables
        """

        def read_formatted_vars(lines):
            """Go over all lines and try to find format variables

            This might be a bit wonky if escaped curly braces are used...
            """
            formatted_var_regex = "(?P<format_var>{.*?})"

            for line in lines:
                for match in re.finditer(formatted_var_regex, line):
                    yield match.group("format_var")

        format_variables = list(read_formatted_vars(code_lines))

        keys = self._get_available_format_keys()

        missing = []

        # Print out values of format variables, like Pytest prints out the
        # values of function call variables
        tw.line("Format variables:", white=True, bold=True)
        for var in format_variables:
            if re.match(r"^\s*\{\}\s*", var):
                continue

            try:
                value_at_call = format_keys(var, keys)
            except exceptions.MissingFormatError:
                missing.append(var)
                value_at_call = "???"
                white = False
                red = True
            else:
                white = True
                red = False

            line = "  {} = '{}'".format(var[1:-1], value_at_call)
            tw.line(line, white=white, red=red)  # pragma: no cover

        return missing

    def _print_test_stage(
        self, tw, code_lines, missing_format_vars, line_start
    ):  # pylint: disable=no-self-use
        """Print the direct source lines from this test stage

        If we couldn't get the stage for some reason, print the entire test out.

        If there are any lines which have missing format variables, higlight
        them in red.

        Args:
            tw (Termin): Pytest TW instance
            code_lines (list(str)): Raw source for this stage
            missing_format_vars (list(str)): List of all missing format
                variables for this stage
            line_start (int): Source line of this stage
        """
        if line_start:
            tw.line(
                "Source test stage (line {}):".format(line_start), white=True, bold=True
            )
        else:
            tw.line("Source test stages:", white=True, bold=True)

        for line in code_lines:
            if any(i in line for i in missing_format_vars):
                tw.line(line, red=True)
            else:
                tw.line(line, white=True)

    def _print_formatted_stage(self, tw, stage):  # pylint: disable=no-self-use
        """Print the 'formatted' stage that Tavern will actually use to send the
        request/process the response

        Args:
            tw (TerminalWriter): Pytest TW instance
            stage (dict): The 'final' stage used by Tavern
        """
        tw.line("Formatted stage:", white=True, bold=True)

        # This will definitely exist
        formatted_lines = yaml.dump(stage, default_flow_style=False).split("\n")

        keys = self._get_available_format_keys()

        for line in formatted_lines:
            if not line:
                continue
            if not "{}" in line:
                line = format_keys(line, keys)
            tw.line("  {}".format(line), white=True)

    def _print_errors(self, tw):
        """Print any errors in the 'normal' Pytest style

        Args:
            tw (TerminalWriter): Pytest TW instance
        """
        tw.line("Errors:", white=True, bold=True)

        # Sort of hack, just use this to directly extract the exception format.
        # If this breaks in future, just re-implement it
        e = FormattedExcinfo()
        lines = e.get_exconly(self.exce)
        for line in lines:
            tw.line(line, red=True, bold=True)

    def toterminal(self, tw):
        """Print out a custom error message to the terminal"""

        # Try to get the stage so we can print it out. I'm not sure if the stage
        # will ever NOT be present, but better to check just in case
        try:
            # pylint: disable=protected-access
            stage = self.exce._excinfo[1].stage
        except AttributeError:
            # Fallback, we don't know which stage it is
            spec = self.item.spec
            stages = spec["stages"]

            first_line = stages[0].start_mark.line - 1
            last_line = stages[-1].end_mark.line
            line_start = None
        else:
            first_line = stage.start_mark.line - 1
            last_line = stage.end_mark.line
            line_start = first_line + 1

        def read_relevant_lines(filename):
            """Get lines between start and end mark"""
            with io.open(filename, "r", encoding="utf8") as testfile:
                for idx, line in enumerate(testfile.readlines()):
                    if idx > first_line and idx < last_line:
                        yield line.rstrip()

        code_lines = list(read_relevant_lines(self.item.spec.start_mark.name))

        missing_format_vars = self._print_format_variables(tw, code_lines)
        tw.line("")

        self._print_test_stage(tw, code_lines, missing_format_vars, line_start)
        tw.line("")

        if not missing_format_vars and stage:
            self._print_formatted_stage(tw, stage)
        else:
            tw.line("Unable to get formatted stage", white=True, bold=True)

        tw.line("")

        self._print_errors(tw)

    @property
    def longreprtext(self):
        tw = py.io.TerminalWriter(stringio=True)  # pylint: disable=no-member
        tw.hasmarkup = False
        self.toterminal(tw)
        exc = tw.stringio.getvalue()
        return exc.strip()

    def __str__(self):
        return self.longreprtext
