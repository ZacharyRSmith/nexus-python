import enum
import bitstring
import siphash

from nexus_keycode.protocols.utils import full_obscure

"""
Nexus Channel Origin Commands. Generated by an 'origin' (typically a backend
server) to update the Nexus Channel security state of one controller and
one or more accessory devices. Origin commands are accepted by controller
devices.

Devices which establish a secured link may access 'secured' resource methods
on other devices (e.g. a controller securely linked to a controller may
POST PAYG credit updates to a linked accessory).

Currently supported operations in `nexus-embedded` (firmware):

    * Create secured link between controller and accessory (`LINK_ACCESSORY_MODE_3`)
    * Delete all secured links from controller (`UNLINK_ALL_ACCESSORIES`)

For corresponding embedded device side logic, see:
https://github.com/angaza/nexus-embedded

For info on Nexus Channel: https://nexus.angaza.com/channel.html
"""


@enum.unique
class ChannelOriginAction(enum.Enum):
    """Business logic list of possible origin command actions."""
    # Delete all accessory links from a controller
    UNLINK_ALL_ACCESSORIES = object()
    # Signal PAYG credit resource 'unlock' for all linked accessories (UNSUPPORTED)
    UNLOCK_ALL_ACCESSORIES = object()
    # Signal PAYG credit resource 'unlock' for one specific accessory (UNSUPPORTED)
    UNLOCK_ACCESSORY = object()
    # Delete link to one specific accessory (UNSUPPORTED)
    UNLINK_ACCESSORY = object()
    # Create Nexus Channel secured link between controller and accessory
    LINK_ACCESSORY_MODE_3 = object()

    def build(self, **kwargs):
        # type: () -> ChannelOriginCommandToken
        """Construct an instance of this message type."""

        cls = type(self)
        constructors = {
            cls.UNLINK_ALL_ACCESSORIES: (
                GenericControllerActionToken.unlink_all_accessories
            ),
            cls.UNLOCK_ALL_ACCESSORIES: (
                GenericControllerActionToken.unlock_all_accessories
            ),
            cls.UNLOCK_ACCESSORY: (
                SpecificLinkedAccessoryToken.unlock_specific_accessory
            ),
            cls.UNLINK_ACCESSORY: (
                SpecificLinkedAccessoryToken.unlink_specific_accessory
            ),
            cls.LINK_ACCESSORY_MODE_3: (
                LinkCommandToken.challenge_mode_3
            ),
        }

        return constructors[self](**kwargs)


@enum.unique
class OriginCommandType(enum.Enum):
    """ Types of Nexus Origin commands that exist.
    Types 0-9 are possible to transmit via keycode. Additional types
    may exist in the future which are not easily transmitted via token.

    This is not called directly; as some business-facing 'types' are actually
    subtypes of the types defined here. The types in this list map
    directly to the "Origin Command Types" defined in the spec.

    This enum should not be used/exposed outside of this module.
    """
    GENERIC_CONTROLLER_ACTION = 0
    UNLOCK_ACCESSORY = 1
    UNLINK_ACCESSORY = 2
    # 3-8 reserved
    LINK_ACCESSORY_MODE_3 = 9


class ChannelOriginCommandToken(object):
    """Data sent from the Nexus Channel origin (backend) to a controller.

    This data is encoded as a string of decimal digits 0-9.

    This data may be packed into a keycode (see `PASSTHROUGH_COMMAND` in
    `keycodev1.py`), or may be transmitted inside any other format.
    It is likely, however, that for more 'advanced' transmission formats,
    we may decide to use a more expressive data format.

    `ChannelOriginCommandTokens` all include appropriate integrity
    checks, and do not make any assumptions about integrity checks provided by
    lower-level transport protocols.

    A `ChannelOriginCommandToken` takes the following form:

    [1-digit command code][N-digit message body][M-digit 'auth' fields]

    These 1+N+M digits are expected to be placed inside the body of a
    lower-level keycode transport protocol - which is responsible for getting
    the `ChannelOriginCommandToken` into a controller through an existing
    keycode protocol.

    :see: :class:`LinkCommand`
    """

    def __init__(self, type_, body, auth):
        """
        :param type_: Type of origin command this token represents
        :type type_: :class:`OriginCommandType`
        :param body: arbitrary digits of message body
        :type body: :class:`str`
        :param auth: arbitrary digits of auth field
        :type auth: :class:`str`
        """
        if not isinstance(type_, OriginCommandType):
            raise TypeError("Must supply valid OriginCommandType.")

        self.type_code = type_.value
        self.body = body
        self.auth = auth

    def __str__(self):
        return self.to_digits()

    def __repr__(self):
        return (
            "{}.{}("
            "{type_code!r}, "
            "{body!r}, "
            "{auth!r},))").format(
            self.__class__.__module__,
            self.__class__.__name__,
            **self.__dict__)

    def to_digits(self, obscured=True):
        # type: (bool) -> str
        # String of digits making up this Nexus Channel "Token".

        result = "{}{}{}".format(
            self.type_code,
            self.body,
            self.auth
        )
        if obscured:
            # obscure all digits except MAC/auth
            obscured_digit_count = len(result) - len(str(self.auth))
            result = full_obscure(result, obscured_digit_count=obscured_digit_count)

        return result

    @staticmethod
    def digits_from_siphash(siphash_function, digits=6):
        """ Return the least-significant digits from a Siphash function.

        Defaults to 6, may be increased.
        """
        format_str = "{{:0{}d}}".format(digits)
        return format_str.format(
            siphash_function.hash() & 0xffffffff
        )[-digits:]


class GenericControllerActionToken(ChannelOriginCommandToken):
    """ Not intended to be instantiated directly.

    see: `unlink_all_accessories`.
    """

    _origin_command_type = OriginCommandType.GENERIC_CONTROLLER_ACTION

    def __init__(
            self,
            type_,
            controller_command,
            auth
    ):
        super(GenericControllerActionToken, self).__init__(
            type_=self._origin_command_type,
            body=controller_command,
            auth=self.digits_from_siphash(auth)
        )

    @enum.unique
    class GenericControllerActionType(enum.Enum):
        """ Types of 'generic controller actions' that are possible.
        Types 0-20 are reserved for Angaza use. Other types may be 'custom'
        as needed.
        """

        # Delete all accessories from the receiving controller
        UNLINK_ALL_ACCESSORIES = 0
        # Unlock all accessories linked to the receiving controller
        UNLOCK_ALL_ACCESSORIES = 1
        # Types 2-99 undefined

    @classmethod
    def _generic_controller_action_builder(
        cls,
        type_,
        controller_command_count,
        controller_sym_key
    ):
        # type: (int, str) -> ChannelOriginCommandToken
        """ Resulting token:

        1-digit Origin Keycode Type ID (0)
        2-digit "Origin Controller Commmand" (0-99)
        6-digit target authentication (auth for controller)
        """
        # Requires 16-byte symmetric Nexus keys
        assert len(controller_sym_key) == 16

        controller_command_value = type_.value

        packed_target_inputs = bitstring.pack(
            [
                "uintle:32=controller_command_count",
                "uintle:8=origin_command_type_code",  # '0'
                "uintle:32=controller_command_value",  # packed as uint32
            ],
            controller_command_count=controller_command_count,
            origin_command_type_code=cls._origin_command_type.value,
            controller_command_value=controller_command_value,
        ).bytes
        assert len(packed_target_inputs) == 9

        auth = siphash.SipHash_2_4(
            controller_sym_key,
            packed_target_inputs)

        return cls(
            type_=type_,
            controller_command="{:02d}".format(controller_command_value),
            auth=auth
        )

    @classmethod
    def unlink_all_accessories(
        cls,
        controller_command_count,
        controller_sym_key
    ):
        return cls._generic_controller_action_builder(
            cls.GenericControllerActionType.UNLINK_ALL_ACCESSORIES,
            controller_command_count,
            controller_sym_key,
        )

    @classmethod
    def unlock_all_accessories(
        cls,
        controller_command_count,
        controller_sym_key
    ):
        return cls._generic_controller_action_builder(
            cls.GenericControllerActionType.UNLOCK_ALL_ACCESSORIES,
            controller_command_count,
            controller_sym_key,
        )


class SpecificLinkedAccessoryToken(ChannelOriginCommandToken):
    def __init__(
            self,
            type_,
            accessory_nexus_id,
            auth
    ):
        # Truncated Nexus ID = least significant one decimal digits
        truncated_accessory_nexus_id = "{:01d}".format(
            (accessory_nexus_id & 0xFFFFFFFF) % 10)
        super(SpecificLinkedAccessoryToken, self).__init__(
            type_=type_,
            body=truncated_accessory_nexus_id,
            auth=self.digits_from_siphash(auth)
        )

    @classmethod
    def _specific_accessory_builder(
        cls,
        type_,
        accessory_nexus_id,
        controller_command_count,
        controller_sym_key
    ):
        # type: (int, int, int, str, str) -> ChannelOriginCommandToken
        """ Resulting token:

        1-digit Origin Keycode Type ID (2)
        1-digit body field (Accessory Nexus ID, truncated)
        6-digit target authentication (MAC)

        Note that the controller cannot validate this command if it does not
        actually have a link to the specified accessory. This is because
        the MAC is generated using the accessory Nexus ID, and thus it must
        'look up' the accessory Nexus ID to validate the message.

        Practically, we can do this by allowing the origin manager to 'ask'
        for the ID of all linked accessories (optionally those matching the
        truncated ID), and attempt to compute the MAC using each of those. If
        there is no match, the message is invalid.

        The expanded 'body' consists of two parts - the Nexus 'authority'
        ID (first 2 bytes of Nexus ID), and the Nexus 'device' ID (last 4 bytes
        of Nexus ID).
        """

        # Requires 16-byte symmetric Nexus keys
        assert len(controller_sym_key) == 16

        # note that these are not 'transmitted' body digits, but it is
        # assumed that the receiver will 'expand' the message (from the
        # transmitted, truncated accessory ID) to then find any linked
        # accessory with a matching device ID, and pull in the full values
        # to use to generate this MAC.

        # vendor / authority ID is upper 2 bytes of the full 'Nexus ID'
        nexus_authority_id = (accessory_nexus_id & 0xFFFF00000000) >> 32
        nexus_device_id = accessory_nexus_id & 0xFFFFFFFF

        packed_target_inputs = bitstring.pack(
            [
                "uintle:32=controller_command_count",
                "uintle:8=origin_command_type_code",  # '2' or '3'
                "uintle:16=nexus_authority_id",
                "uintle:32=nexus_device_id",
            ],
            controller_command_count=controller_command_count,
            origin_command_type_code=type_.value,
            nexus_authority_id=nexus_authority_id,
            nexus_device_id=nexus_device_id
        ).bytes

        assert len(packed_target_inputs) == 11
        auth = siphash.SipHash_2_4(
            controller_sym_key,
            packed_target_inputs
        )

        return cls(
            type_=type_,
            accessory_nexus_id=accessory_nexus_id,
            auth=auth
        )

    @classmethod
    def unlink_specific_accessory(
            cls,
            accessory_nexus_id,
            controller_command_count,
            controller_sym_key
    ):
        return cls._specific_accessory_builder(
            OriginCommandType.UNLINK_ACCESSORY,
            accessory_nexus_id,
            controller_command_count,
            controller_sym_key
        )

    @classmethod
    def unlock_specific_accessory(
            cls,
            accessory_nexus_id,
            controller_command_count,
            controller_sym_key
    ):
        return cls._specific_accessory_builder(
            OriginCommandType.UNLOCK_ACCESSORY,
            accessory_nexus_id,
            controller_command_count,
            controller_sym_key
        )


class LinkCommandToken(ChannelOriginCommandToken):

    _origin_command_type = OriginCommandType.LINK_ACCESSORY_MODE_3

    def __init__(
            self,
            type_,
            body,
            auth
    ):
        super(LinkCommandToken, self).__init__(
            type_=type_,
            body=body,
            auth=auth)

    @classmethod
    def challenge_mode_3(
            cls,
            controller_command_count,
            accessory_command_count,
            accessory_sym_key,
            controller_sym_key):
        # type: (int, int, str, str) -> ChannelOriginCommandToken
        """ Resulting token:

        1-digit Origin Keycode Type ID (9)
        6-digit body (6 "Challenge Result" digits)
        6-digit auth (controller authentication)
        """

        command_type = OriginCommandType.LINK_ACCESSORY_MODE_3

        # Requires 16-byte symmetric Nexus keys
        assert len(accessory_sym_key) == 16
        assert len(controller_sym_key) == 16

        # this auth is the 'challenge result' which accessory will validate
        packed_target_inputs = bitstring.pack(
            ["uintle:32=accessory_command_count"],
            accessory_command_count=int(accessory_command_count)
        ).bytes
        assert len(packed_target_inputs) == 4
        accessory_auth = siphash.SipHash_2_4(
            accessory_sym_key,
            packed_target_inputs
        )

        # 6-digits
        accessory_auth_digits = cls.digits_from_siphash(accessory_auth)

        # This auth is used by the receiver of the origin command.
        # the receiver (controller) will unpack the challenge digits as
        # a message 'body', and recompute a MAC using these. Only if the
        # computed MAC is valid (matches the transmitted MAC)
        # will the challenge digits be passed onward to the accessory.
        packed_auth_inputs = bitstring.pack(
            [
                "uintle:32=controller_command_count",
                "uintle:8=command_type_code",  # '9'
                "uintle:32=challenge_digits_int",  # challenge digits as int
            ],
            controller_command_count=controller_command_count,
            command_type_code=command_type.value,
            challenge_digits_int=int(accessory_auth_digits)
        )
        assert len(packed_auth_inputs.tobytes()) == 9

        auth = siphash.SipHash_2_4(
            controller_sym_key,
            packed_auth_inputs.bytes)

        return cls(
            type_=command_type,
            body=accessory_auth_digits,
            auth=cls.digits_from_siphash(auth)
        )
