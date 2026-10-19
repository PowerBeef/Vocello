// Strict memory safety across two Swift toolchains (DW-04). Swift 6.4 annotates
// Array.withUnsafeBufferPointer, Array.withUnsafeMutableBufferPointer and withUnsafeBytes(of:)
// @safe; Swift 6.3, in CI's required Xcode 26.6, does not. A call to one of them needs an
// `unsafe` marker under 6.3 that 6.4 reports as unnecessary, and warnings are errors on both.
// These @safe forwards absorb the difference in one place: each spells its one call the way the
// compiler building it requires, and their callers need no marker under either toolchain.
// Retire them, and use the standard library names again, once CI builds with Xcode 27.

extension Array {
    /// `withUnsafeBufferPointer` that needs no `unsafe` marker under Swift 6.3 or 6.4.
    @safe @inlinable
    public func withBufferPointer<Result>(
        _ body: (UnsafeBufferPointer<Element>) throws -> Result
    ) rethrows -> Result {
#if compiler(>=6.4)
        try withUnsafeBufferPointer(body)
#else
        unsafe try withUnsafeBufferPointer(body)
#endif
    }

    /// `withUnsafeMutableBufferPointer` that needs no `unsafe` marker under Swift 6.3 or 6.4.
    @safe @inlinable
    public mutating func withMutableBufferPointer<Result>(
        _ body: (inout UnsafeMutableBufferPointer<Element>) throws -> Result
    ) rethrows -> Result {
#if compiler(>=6.4)
        try withUnsafeMutableBufferPointer(body)
#else
        unsafe try withUnsafeMutableBufferPointer(body)
#endif
    }
}

/// `withUnsafeBytes(of:_:)` that needs no `unsafe` marker under Swift 6.3 or 6.4.
@safe @inlinable
public func withValueBytes<T, Result>(
    of value: T,
    _ body: (UnsafeRawBufferPointer) throws -> Result
) rethrows -> Result {
#if compiler(>=6.4)
    try withUnsafeBytes(of: value, body)
#else
    unsafe try withUnsafeBytes(of: value, body)
#endif
}

/// `withUnsafeBytes(of: &value, _:)` that needs no `unsafe` marker under Swift 6.3 or 6.4.
@safe @inlinable
public func withValueBytes<T, Result>(
    of value: inout T,
    _ body: (UnsafeRawBufferPointer) throws -> Result
) rethrows -> Result {
#if compiler(>=6.4)
    try withUnsafeBytes(of: &value, body)
#else
    unsafe try withUnsafeBytes(of: &value, body)
#endif
}
