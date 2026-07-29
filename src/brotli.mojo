"""Brotli encoder and decoder bindings exposed through a stable C ABI."""

from std.ffi import external_call

comptime BPtr = UnsafePointer[UInt8, AnyOrigin[mut=True]]
comptime IPtr = UnsafePointer[Int, AnyOrigin[mut=True]]


@export("mb_encoder_version")
def mb_encoder_version() abi("C") -> Int:
    return Int(external_call["BrotliEncoderVersion", UInt32]())


@export("mb_decoder_version")
def mb_decoder_version() abi("C") -> Int:
    return Int(external_call["BrotliDecoderVersion", UInt32]())


@export("mb_encoder_max_compressed_size")
def mb_encoder_max_compressed_size(input_size: Int) abi("C") -> Int:
    if input_size < 0:
        return 0
    return external_call["BrotliEncoderMaxCompressedSize", Int](input_size)


@export("mb_encoder_compress")
def mb_encoder_compress(
    quality: Int,
    lgwin: Int,
    mode: Int,
    input_size: Int,
    input_address: Int,
    encoded_size_address: Int,
    encoded_address: Int,
) abi("C") -> Int:
    if (
        quality < 0
        or quality > 11
        or lgwin < 10
        or lgwin > 24
        or mode < 0
        or mode > 2
        or input_size < 0
        or (input_size != 0 and input_address == 0)
        or encoded_size_address == 0
        or encoded_address == 0
    ):
        return 0
    return Int(
        external_call["BrotliEncoderCompress", Int32](
            Int32(quality),
            Int32(lgwin),
            Int32(mode),
            input_size,
            input_address,
            encoded_size_address,
            encoded_address,
        )
    )


@export("mb_encoder_compress_alloc")
def mb_encoder_compress_alloc(
    quality: Int,
    lgwin: Int,
    mode: Int,
    input_size: Int,
    input_address: Int,
    encoded_address_address: Int,
    encoded_size_address: Int,
) abi("C") -> Int:
    if (
        quality < 0
        or quality > 11
        or lgwin < 10
        or lgwin > 24
        or mode < 0
        or mode > 2
        or input_size < 0
        or (input_size != 0 and input_address == 0)
        or encoded_address_address == 0
        or encoded_size_address == 0
    ):
        return 0
    var capacity = external_call["BrotliEncoderMaxCompressedSize", Int](
        input_size
    )
    if capacity <= 0:
        return 0
    var encoded_address = external_call["malloc", Int](capacity)
    if encoded_address == 0:
        return 0
    var encoded_size = capacity
    var succeeded = external_call["BrotliEncoderCompress", Int32](
        Int32(quality),
        Int32(lgwin),
        Int32(mode),
        input_size,
        input_address,
        Int(UnsafePointer(to=encoded_size)),
        encoded_address,
    )
    if succeeded == 0:
        external_call["free", NoneType](encoded_address)
        return 0
    IPtr(unsafe_from_address=encoded_address_address)[] = encoded_address
    IPtr(unsafe_from_address=encoded_size_address)[] = encoded_size
    return 1


@export("mb_encoder_create")
def mb_encoder_create(mode: Int, quality: Int, lgwin: Int, lgblock: Int) abi("C") -> Int:
    if (
        mode < 0
        or mode > 2
        or quality < 0
        or quality > 11
        or lgwin < 10
        or lgwin > 24
        or (lgblock != 0 and (lgblock < 16 or lgblock > 24))
    ):
        return 0
    var state = external_call["BrotliEncoderCreateInstance", Int](
        Int(0), Int(0), Int(0)
    )
    if state == 0:
        return 0
    if external_call["BrotliEncoderSetParameter", Int32](
        state, Int32(0), UInt32(mode)
    ) == 0:
        external_call["BrotliEncoderDestroyInstance", NoneType](state)
        return 0
    if external_call["BrotliEncoderSetParameter", Int32](
        state, Int32(1), UInt32(quality)
    ) == 0:
        external_call["BrotliEncoderDestroyInstance", NoneType](state)
        return 0
    if external_call["BrotliEncoderSetParameter", Int32](
        state, Int32(2), UInt32(lgwin)
    ) == 0:
        external_call["BrotliEncoderDestroyInstance", NoneType](state)
        return 0
    if lgblock != 0:
        if external_call["BrotliEncoderSetParameter", Int32](
            state, Int32(3), UInt32(lgblock)
        ) == 0:
            external_call["BrotliEncoderDestroyInstance", NoneType](state)
            return 0
    return state


@export("mb_encoder_destroy")
def mb_encoder_destroy(state: Int) abi("C"):
    external_call["BrotliEncoderDestroyInstance", NoneType](state)


@export("mb_encoder_stream")
def mb_encoder_stream(
    state: Int,
    operation: Int,
    available_input_address: Int,
    next_input_address: Int,
    available_output_address: Int,
    next_output_address: Int,
) abi("C") -> Int:
    if (
        state == 0
        or operation < 0
        or operation > 2
        or available_input_address == 0
        or next_input_address == 0
        or available_output_address == 0
        or next_output_address == 0
    ):
        return 0
    return Int(
        external_call["BrotliEncoderCompressStream", Int32](
            state,
            Int32(operation),
            available_input_address,
            next_input_address,
            available_output_address,
            next_output_address,
            Int(0),
        )
    )


@export("mb_encoder_has_more_output")
def mb_encoder_has_more_output(state: Int) abi("C") -> Int:
    return Int(external_call["BrotliEncoderHasMoreOutput", Int32](state))


@export("mb_encoder_is_finished")
def mb_encoder_is_finished(state: Int) abi("C") -> Int:
    return Int(external_call["BrotliEncoderIsFinished", Int32](state))


@export("mb_decoder_create")
def mb_decoder_create() abi("C") -> Int:
    return external_call["BrotliDecoderCreateInstance", Int](
        Int(0), Int(0), Int(0)
    )


@export("mb_decoder_destroy")
def mb_decoder_destroy(state: Int) abi("C"):
    external_call["BrotliDecoderDestroyInstance", NoneType](state)


@export("mb_decoder_stream")
def mb_decoder_stream(
    state: Int,
    available_input_address: Int,
    next_input_address: Int,
    available_output_address: Int,
    next_output_address: Int,
) abi("C") -> Int:
    if (
        state == 0
        or available_input_address == 0
        or next_input_address == 0
        or available_output_address == 0
        or next_output_address == 0
    ):
        return 0
    return Int(
        external_call["BrotliDecoderDecompressStream", Int32](
            state,
            available_input_address,
            next_input_address,
            available_output_address,
            next_output_address,
            Int(0),
        )
    )


@export("mb_decoder_decompress_alloc")
def mb_decoder_decompress_alloc(
    input_size: Int,
    input_address: Int,
    decoded_address_address: Int,
    decoded_size_address: Int,
) abi("C") -> Int:
    if (
        input_size < 0
        or input_address == 0
        or decoded_address_address == 0
        or decoded_size_address == 0
    ):
        return 0
    var state = external_call["BrotliDecoderCreateInstance", Int](
        Int(0), Int(0), Int(0)
    )
    if state == 0:
        return 0
    var capacity = max(Int(1024 * 1024), input_size)
    var decoded_address = external_call["malloc", Int](capacity)
    if decoded_address == 0:
        external_call["BrotliDecoderDestroyInstance", NoneType](state)
        return 0
    var available_input = input_size
    var next_input = BPtr(unsafe_from_address=input_address)
    var produced = Int(0)
    while True:
        var available_output = capacity - produced
        var next_output = BPtr(unsafe_from_address=decoded_address + produced)
        var result = Int(
            external_call["BrotliDecoderDecompressStream", Int32](
                state,
                Int(UnsafePointer(to=available_input)),
                Int(UnsafePointer(to=next_input)),
                Int(UnsafePointer(to=available_output)),
                Int(UnsafePointer(to=next_output)),
                Int(0),
            )
        )
        produced = capacity - available_output
        if result == 1:
            if available_input != 0:
                external_call["free", NoneType](decoded_address)
                external_call["BrotliDecoderDestroyInstance", NoneType](state)
                return 0
            IPtr(unsafe_from_address=decoded_address_address)[] = decoded_address
            IPtr(unsafe_from_address=decoded_size_address)[] = produced
            external_call["BrotliDecoderDestroyInstance", NoneType](state)
            return 1
        if result != 3:
            external_call["free", NoneType](decoded_address)
            external_call["BrotliDecoderDestroyInstance", NoneType](state)
            return 0
        var new_capacity = capacity * 2
        if new_capacity <= capacity:
            external_call["free", NoneType](decoded_address)
            external_call["BrotliDecoderDestroyInstance", NoneType](state)
            return 0
        var replacement = external_call["realloc", Int](
            decoded_address, new_capacity
        )
        if replacement == 0:
            external_call["free", NoneType](decoded_address)
            external_call["BrotliDecoderDestroyInstance", NoneType](state)
            return 0
        decoded_address = replacement
        capacity = new_capacity


@export("mb_free")
def mb_free(address: Int) abi("C"):
    if address != 0:
        external_call["free", NoneType](address)


@export("mb_decoder_is_finished")
def mb_decoder_is_finished(state: Int) abi("C") -> Int:
    return Int(external_call["BrotliDecoderIsFinished", Int32](state))


@export("mb_decoder_error_code")
def mb_decoder_error_code(state: Int) abi("C") -> Int:
    return Int(external_call["BrotliDecoderGetErrorCode", Int32](state))
