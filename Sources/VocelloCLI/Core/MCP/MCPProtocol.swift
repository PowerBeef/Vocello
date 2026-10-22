import Foundation

/// The Model Context Protocol as `vocello mcp` speaks it (RF-29): JSON-RPC 2.0,
/// one message per line on stdio. Both eras are served, as the 2026-07-28
/// revision allows a dual-era server to: a request whose `_meta` names a
/// stateless revision is served on its own, and an `initialize` handshake
/// selects an earlier revision for the rest of the process.
public enum MCPProtocol {
    /// Stateless revisions: every request names one in `_meta`.
    public static let modernVersions = ["2026-07-28"]
    /// Revisions an `initialize` handshake may choose, newest first.
    public static let legacyVersions = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
    public static var allVersions: [String] { modernVersions + legacyVersions }

    static let protocolVersionKey = "io.modelcontextprotocol/protocolVersion"
    static let serverInfoKey = "io.modelcontextprotocol/serverInfo"

    /// JSON-RPC's codes and the protocol's own.
    enum ErrorCode: Int, Sendable {
        case parseError = -32700
        case invalidRequest = -32600
        case methodNotFound = -32601
        case invalidParams = -32602
        case internalError = -32603
        case unsupportedProtocolVersion = -32022
    }

    /// The revision an `initialize` naming `requested` is answered with: the
    /// same one when it is served, else the newest.
    static func legacyVersion(answering requested: String?) -> String {
        requested.flatMap { legacyVersions.contains($0) ? $0 : nil } ?? legacyVersions[0]
    }
}

/// A JSON-RPC error answered to the client.
struct MCPRPCError: Error, Sendable, Equatable {
    let code: MCPProtocol.ErrorCode
    let message: String
    var data: CLIJSONValue?
    /// The request it answers; null when the request's id could not be read.
    var id: CLIJSONValue = .null
}

/// One JSON-RPC message from the client.
struct MCPIncoming: Sendable, Equatable {
    enum Kind: Sendable, Equatable {
        case request(id: CLIJSONValue)
        case notification
        /// A response: the server sends no requests, so it is ignored.
        case response
    }

    let kind: Kind
    let method: String
    let params: [String: CLIJSONValue]

    var meta: [String: CLIJSONValue] {
        if case .object(let meta)? = params["_meta"] { return meta }
        return [:]
    }

    /// The revision a stateless request names.
    var protocolVersion: String? {
        if case .string(let version)? = meta[MCPProtocol.protocolVersionKey] { return version }
        return nil
    }

    /// Parses one line. A line that is not a JSON-RPC 2.0 message fails with
    /// the error to answer it with (null id unless the id could be read).
    static func parse(_ line: String) -> Result<MCPIncoming, MCPRPCError> {
        guard let value = try? JSONDecoder().decode(CLIJSONValue.self, from: Data(line.utf8)) else {
            return .failure(MCPRPCError(code: .parseError, message: "the line is not JSON"))
        }
        guard case .object(let object) = value else {
            // A batch (an array) was removed from the protocol in 2025-06-18.
            return .failure(MCPRPCError(code: .invalidRequest, message: "a message is one JSON-RPC object"))
        }
        let id = object["id"]
        var readableID = CLIJSONValue.null
        if let id {
            switch id {
            case .string, .integer, .unsigned: readableID = id
            default:
                return .failure(MCPRPCError(code: .invalidRequest, message: "an id is a string or an integer"))
            }
        }
        guard case .string("2.0")? = object["jsonrpc"] else {
            return .failure(MCPRPCError(code: .invalidRequest, message: "jsonrpc must be \"2.0\"", id: readableID))
        }
        guard case .string(let method)? = object["method"] else {
            if id != nil, object["result"] != nil || object["error"] != nil {
                return .success(MCPIncoming(kind: .response, method: "", params: [:]))
            }
            return .failure(MCPRPCError(code: .invalidRequest, message: "a request names its method", id: readableID))
        }
        var params: [String: CLIJSONValue] = [:]
        switch object["params"] {
        case nil, .null?: break
        case .object(let given)?: params = given
        default:
            return .failure(MCPRPCError(code: .invalidParams, message: "params is an object", id: readableID))
        }
        return .success(MCPIncoming(kind: id.map { .request(id: $0) } ?? .notification, method: method, params: params))
    }
}

/// The messages the server writes.
enum MCPOutgoing {
    static func result(id: CLIJSONValue, _ result: CLIJSONValue) -> CLIJSONValue {
        .object(["jsonrpc": "2.0", "id": id, "result": result])
    }

    static func error(_ error: MCPRPCError) -> CLIJSONValue {
        var body: [String: CLIJSONValue] = ["code": .integer(error.code.rawValue), "message": .string(error.message)]
        if let data = error.data { body["data"] = data }
        return .object(["jsonrpc": "2.0", "id": error.id, "error": .object(body)])
    }

    static func notification(_ method: String, _ params: [String: CLIJSONValue]) -> CLIJSONValue {
        .object(["jsonrpc": "2.0", "method": .string(method), "params": .object(params)])
    }

    /// One message as a line: compact JSON, which never holds a raw newline. A
    /// reply that cannot be encoded becomes an error for its request, so the
    /// client never waits on it; such a notification is dropped.
    static func line(_ message: CLIJSONValue) -> Data {
        if let line = try? CLIJSONEncoding.line(message) { return line }
        guard case .object(let fields) = message, let id = fields["id"] else { return Data() }
        let fallback = error(MCPRPCError(code: .internalError, message: "the reply could not be encoded as JSON", id: id))
        return (try? CLIJSONEncoding.line(fallback)) ?? Data()
    }
}
