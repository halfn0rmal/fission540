#pragma once

// Reader for Autodesk ShapeManager binary B-rep ("ASM BinaryFile4", .smb),
// which is token-compatible with ACIS SAB. Format notes: docs/formats/f3d.md.

#include "fission/io/ZipArchive.h"

#include <array>
#include <cstdint>
#include <span>
#include <string>
#include <vector>

namespace fission::io::sab {

enum class TokenKind : std::uint8_t {
    Char,
    Short,
    Long,
    Float,
    Double,
    String,
    Ident,
    SubIdent,
    True,
    False,
    Ref,
    Position,
    Vector,
    Vector2,
    Enum,
    SubtypeOpen,
    SubtypeClose,
};

struct Token {
    TokenKind kind{};
    std::int64_t i = 0;               // Char/Short/Long/Ref/Enum
    std::array<double, 3> d{};        // Float/Double (d[0]), Position/Vector/Vector2
    std::string s;                    // String/Ident/SubIdent

    [[nodiscard]] bool isNumber() const {
        return kind == TokenKind::Double || kind == TokenKind::Float || kind == TokenKind::Long ||
               kind == TokenKind::Short || kind == TokenKind::Char || kind == TokenKind::Enum;
    }
    [[nodiscard]] double number() const;
};

struct Record {
    // Class name with sub-identifiers joined by '-', e.g. "cone-surface", "edge".
    std::string type;
    // Tokens after the class identifiers, terminator excluded.
    std::vector<Token> values;
};

struct Document {
    std::int64_t version = 0;
    // Number of top-level saved entities, counting the asmheader. They are records
    // [0, entityCount); everything after is owned by them (e.g. feature caches).
    int entityCount = 0;
    std::string product;
    std::string asmVersion;
    std::string date;
    double mmPerUnit = 1.0; // Fusion stores cm: 10.0
    double resabs = 1e-6;
    double resnor = 1e-10;
    std::vector<Record> records;
};

class SabError : public IoError {
public:
    using IoError::IoError;
};

[[nodiscard]] bool hasMagic(std::span<const std::uint8_t> data);

// Parses all model records up to the history section.
[[nodiscard]] Document parse(std::span<const std::uint8_t> data);

} // namespace fission::io::sab
