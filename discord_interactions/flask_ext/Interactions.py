#!/usr/bin/env python

"""
MIT License

Copyright (c) 2020-2021 Linus Bartsch

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from flask import Flask, request, jsonify
from discord_interactions import (
    Interaction,
    InteractionType,
    InteractionResponse,
    InteractionResponseType,
    InteractionApplicationCommandCallbackData,
    verify_key,
    ApplicationCommand,
)
from discord_interactions import ocm
from typing import Callable, Union, Type, Dict, List


_CommandCallback = Callable[
    [Union[Interaction, ocm.Command]], Union[InteractionResponse, str, None]
]


class Interactions:
    def __init__(self, app: Flask, public_key: str):
        self._app = app
        self._public_key = public_key

        app.add_url_rule("/", "interactions", self._main, methods=["POST"])

        self._commands: Dict[str, ApplicationCommand] = {}
        self._callbacks: Dict[str, _CommandCallback] = {}

    @property
    def commands(self) -> List[ApplicationCommand]:
        """ All registered application commands """

        return list(self._commands.values())

    def _verify_request(self):
        signature = request.headers.get("X-Signature-Ed25519")
        timestamp = request.headers.get("X-Signature-Timestamp")

        if signature is None or timestamp is None:
            return False

        return verify_key(request.data, signature, timestamp, self._public_key)

    def _main(self):
        # Verify request
        if not self._app.config["TESTING"]:
            if not self._verify_request():
                return "Bad request signature", 401

        # Handle interactions
        interaction = Interaction(**request.json)

        if interaction.type == InteractionType.PING:
            return jsonify(InteractionResponse(InteractionResponseType.PONG).to_dict())
        elif interaction.type == InteractionType.APPLICATION_COMMAND:
            cmd = interaction.data.name
            cb = self._callbacks[cmd]

            cb_data = interaction
            if len(annotations := cb.__annotations__.values()) > 0:
                cmd_type = next(iter(annotations))
                if issubclass(cmd_type, ocm.Command):
                    cb_data = cmd_type.wrap(interaction)

            resp = cb(cb_data)

            if isinstance(resp, InteractionResponse):
                interaction_response = resp
            elif resp is None:
                interaction_response = InteractionResponse(
                    response_type=InteractionResponseType.ACKNOWLEDGE_WITH_SOURCE
                )
            else:
                interaction_response = InteractionResponse(
                    response_type=InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
                    data=InteractionApplicationCommandCallbackData(content=str(resp)),
                )

            return jsonify(interaction_response.to_dict())

        else:
            return "Unknown interaction type", 501

    def register_command(
        self,
        command: Union[ApplicationCommand, Type[ocm.Command], str],
        callback: _CommandCallback,
    ):
        if isinstance(command, ApplicationCommand):
            self._commands[command.name] = command
            self._callbacks[command.name] = callback
        elif issubclass(command, ocm.Command):
            self._commands[command.__cmd_name__] = command.to_application_command()
            self._callbacks[command.__cmd_name__] = callback
        else:
            self._callbacks[command] = callback

    def command(
        self,
        command: Union[ApplicationCommand, str] = None,
        _f: _CommandCallback = None,
    ):
        """
        A decorator to register a slash command.
        Calls :meth:`register_command` internally.
        """

        def decorator(f: _CommandCallback):
            if command is not None:
                self.register_command(command, f)
            elif len(annotations := f.__annotations__.values()) > 0:
                _command = next(
                    iter(annotations)
                )  # get :class:`ocm.Command` from type annotation
                self.register_command(_command, f)
            else:
                self.register_command(f.__name__.lower().strip("_"), f)

        return decorator(_f) if _f is not None else decorator
