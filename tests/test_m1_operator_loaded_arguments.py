"""Exact launchd command evidence; all observations are synthetic."""
import unittest

from scripts.m1_operator_release_host import _loaded_arguments_match, _loaded_definition_match


class LoadedArgumentsTests(unittest.TestCase):
    args = ["/opt/homebrew/bin/python3.12", "-B",
            "/private/owner release/scripts/operator_server.py",
            "--config", "/private/config.json"]

    def output(self, args=None, program=None):
        args = self.args if args is None else args
        program = self.args[0] if program is None else program
        return ("service = {\n\tprogram = " + program +
                "\n\targuments = {\n\t\t" + "\n\t\t".join(args) +
                "\n\t}\n\tpid = 123\n}\n")

    def test_exact_arguments_preserve_spaces(self):
        self.assertTrue(_loaded_arguments_match(self.output(), self.args))

    def test_incidental_or_suffixed_script_path_is_rejected(self):
        self.assertFalse(_loaded_arguments_match(
            "program = " + self.args[2], self.args))
        changed = list(self.args)
        changed[2] += ".unreviewed"
        self.assertFalse(_loaded_arguments_match(self.output(changed), self.args))

    def test_changed_interpreter_options_or_config_is_rejected(self):
        for index in (0, 1, 4):
            changed = list(self.args)
            changed[index] += "-changed"
            self.assertFalse(_loaded_arguments_match(self.output(changed), self.args))
        self.assertFalse(_loaded_arguments_match(
            self.output(program="/another/python"), self.args))

    def test_missing_duplicate_or_extra_arguments_are_rejected(self):
        for args in (self.args[:-1], self.args + ["--unreviewed"]):
            self.assertFalse(_loaded_arguments_match(self.output(args), self.args))
        self.assertFalse(_loaded_arguments_match(self.output() + self.output(), self.args))

    def test_loaded_directory_and_environment_must_match(self):
        definition = {"ProgramArguments": self.args,
                      "WorkingDirectory": "/private/owner release",
                      "EnvironmentVariables": {"PYTHONPATH": "/private/pinned/src"}}
        output = (self.output() + "working directory = /private/owner release\n"
                  "environment = {\nPYTHONPATH => /private/pinned/src\n}\n")
        self.assertTrue(_loaded_definition_match(output, definition))
        for changed in (
                output.replace("/private/pinned/src", "/unreviewed/src"),
                output.replace("working directory = /private/owner release",
                               "working directory = /unreviewed"),
                output.replace("environment = {", "environment = {\nPYTHONHOME => /other"),
                output.replace("environment = {", "environment = {\nPYTHONPATH => /duplicate")):
            self.assertFalse(_loaded_definition_match(changed, definition))


if __name__ == "__main__":
    unittest.main()
