/**
 * Compact pure-JavaScript QR Code generator for Mangasurf.
 * Generates clean SVG string for URLs and text (Byte Mode, ECC Level M/L).
 * Zero external dependencies.
 */

(function(root, factory) {
    if (typeof exports === 'object') module.exports = factory();
    else if (typeof define === 'function' && define.amd) define([], factory);
    else root.QRCode = factory();
})(typeof self !== 'undefined' ? self : this, function() {

    // Reed-Solomon GF(256) tables
    const EXP = new Uint8Array(512);
    const LOG = new Uint8Array(256);
    let x = 1;
    for (let i = 0; i < 255; i++) {
        EXP[i] = x;
        EXP[i + 255] = x;
        LOG[x] = i;
        x = (x << 1) ^ (x >= 128 ? 0x11d : 0);
    }

    function gmul(a, b) {
        if (a === 0 || b === 0) return 0;
        return EXP[LOG[a] + LOG[b]];
    }

    function polyMul(p1, p2) {
        const res = new Uint8Array(p1.length + p2.length - 1);
        for (let i = 0; i < p1.length; i++) {
            for (let j = 0; j < p2.length; j++) {
                res[i + j] ^= gmul(p1[i], p2[j]);
            }
        }
        return res;
    }

    function polyRest(dividend, divisor) {
        let res = new Uint8Array(dividend);
        for (let i = 0; i < dividend.length - divisor.length + 1; i++) {
            const coef = res[i];
            if (coef !== 0) {
                for (let j = 0; j < divisor.length; j++) {
                    res[i + j] ^= gmul(divisor[j], coef);
                }
            }
        }
        return res.slice(dividend.length - divisor.length + 1);
    }

    function getGeneratorPoly(numECBytes) {
        let g = new Uint8Array([1]);
        for (let i = 0; i < numECBytes; i++) {
            g = polyMul(g, new Uint8Array([1, EXP[i]]));
        }
        return g;
    }

    // Version definitions (Version 1 to 6, sufficient for up to 134 bytes at ECC-L / 106 bytes at ECC-M)
    const VERSIONS = [
        null,
        { version: 1, size: 21, totalData: 19, ecBytes: 7, totalBytes: 26, align: [] },
        { version: 2, size: 25, totalData: 34, ecBytes: 10, totalBytes: 44, align: [6, 18] },
        { version: 3, size: 29, totalData: 55, ecBytes: 15, totalBytes: 70, align: [6, 22] },
        { version: 4, size: 33, totalData: 80, ecBytes: 20, totalBytes: 100, align: [6, 26] },
        { version: 5, size: 37, totalData: 108, ecBytes: 26, totalBytes: 134, align: [6, 30] },
        { version: 6, size: 41, totalData: 136, ecBytes: 18 * 2, totalBytes: 172, align: [6, 34] },
    ];

    function pickVersion(dataLen) {
        for (let v = 1; v < VERSIONS.length; v++) {
            const capacity = VERSIONS[v].totalData - 2; // -2 for header & length
            if (dataLen <= capacity) return VERSIONS[v];
        }
        return VERSIONS[VERSIONS.length - 1];
    }

    function createQRCodeSVG(text, { size = 200, margin = 2, fill = "#ffffff", color = "#000000" } = {}) {
        const utf8Bytes = [];
        for (let i = 0; i < text.length; i++) {
            let code = text.charCodeAt(i);
            if (code < 0x80) utf8Bytes.push(code);
            else if (code < 0x800) utf8Bytes.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
            else utf8Bytes.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
        }

        const vInfo = pickVersion(utf8Bytes.length);
        const matrixSize = vInfo.size;
        const matrix = Array.from({ length: matrixSize }, () => Array(matrixSize).fill(null));
        const isReserved = Array.from({ length: matrixSize }, () => Array(matrixSize).fill(false));

        function setFinder(r, c) {
            for (let i = -1; i <= 7; i++) {
                for (let j = -1; j <= 7; j++) {
                    const nr = r + i, nc = c + j;
                    if (nr < 0 || nr >= matrixSize || nc < 0 || nc >= matrixSize) continue;
                    isReserved[nr][nc] = true;
                    if (i === -1 || i === 7 || j === -1 || j === 7) matrix[nr][nc] = 0;
                    else if (i === 0 || i === 6 || j === 0 || j === 6) matrix[nr][nc] = 1;
                    else if (i >= 2 && i <= 4 && j >= 2 && j <= 4) matrix[nr][nc] = 1;
                    else matrix[nr][nc] = 0;
                }
            }
        }

        // 1. Finder patterns
        setFinder(0, 0);
        setFinder(0, matrixSize - 7);
        setFinder(matrixSize - 7, 0);

        // 2. Alignment patterns
        if (vInfo.align && vInfo.align.length > 0) {
            for (const ar of vInfo.align) {
                for (const ac of vInfo.align) {
                    if (isReserved[ar][ac]) continue;
                    for (let i = -2; i <= 2; i++) {
                        for (let j = -2; j <= 2; j++) {
                            const nr = ar + i, nc = ac + j;
                            isReserved[nr][nc] = true;
                            if (Math.abs(i) === 2 || Math.abs(j) === 2 || (i === 0 && j === 0)) matrix[nr][nc] = 1;
                            else matrix[nr][nc] = 0;
                        }
                    }
                }
            }
        }

        // 3. Timing patterns
        for (let i = 8; i < matrixSize - 8; i++) {
            if (!isReserved[6][i]) { matrix[6][i] = i % 2 === 0 ? 1 : 0; isReserved[6][i] = true; }
            if (!isReserved[i][6]) { matrix[i][6] = i % 2 === 0 ? 1 : 0; isReserved[i][6] = true; }
        }

        // Dark module
        matrix[4 * vInfo.version + 9][8] = 1;
        isReserved[4 * vInfo.version + 9][8] = true;

        // Reserve Format Information Area
        for (let i = 0; i < 9; i++) {
            if (i < matrixSize) { isReserved[8][i] = true; isReserved[i][8] = true; }
        }
        for (let i = matrixSize - 8; i < matrixSize; i++) {
            if (i >= 0) { isReserved[8][i] = true; isReserved[i][8] = true; }
        }

        // 4. Encode Data (Byte Mode 0100)
        const bitBuffer = [];
        function writeBits(val, len) {
            for (let i = len - 1; i >= 0; i--) bitBuffer.push((val >> i) & 1);
        }

        writeBits(4, 4); // Byte mode
        writeBits(utf8Bytes.length, 8); // Length
        for (const b of utf8Bytes) writeBits(b, 8);
        writeBits(0, 4); // Terminator

        while (bitBuffer.length % 8 !== 0) bitBuffer.push(0);

        const dataBytes = [];
        for (let i = 0; i < bitBuffer.length; i += 8) {
            let b = 0;
            for (let j = 0; j < 8; j++) b = (b << 1) | bitBuffer[i + j];
            dataBytes.push(b);
        }

        const padBytes = [0xec, 0x11];
        let p = 0;
        while (dataBytes.length < vInfo.totalData) {
            dataBytes.push(padBytes[p++ % 2]);
        }

        // 5. Reed-Solomon Error Correction
        const gen = getGeneratorPoly(vInfo.ecBytes);
        const augmented = new Uint8Array(vInfo.totalData + vInfo.ecBytes);
        augmented.set(dataBytes);
        const ecBytes = polyRest(augmented, gen);

        const finalBytes = dataBytes.concat(Array.from(ecBytes));
        const finalBits = [];
        for (const b of finalBytes) {
            for (let i = 7; i >= 0; i--) finalBits.push((b >> i) & 1);
        }

        // 6. Populate Matrix with Mask Pattern 0: (row + col) % 2 === 0
        let bitIdx = 0;
        let right = matrixSize - 1;
        let upwards = true;

        while (right > 0) {
            if (right === 6) right--; // Skip vertical timing pattern
            for (let vert = 0; vert < matrixSize; vert++) {
                const r = upwards ? (matrixSize - 1 - vert) : vert;
                for (let c = right; c >= right - 1; c--) {
                    if (!isReserved[r][c]) {
                        const bit = bitIdx < finalBits.length ? finalBits[bitIdx++] : 0;
                        const mask = (r + c) % 2 === 0;
                        matrix[r][c] = (bit ^ (mask ? 1 : 0));
                    }
                }
            }
            right -= 2;
            upwards = !upwards;
        }

        // 7. Write Format Information (Mask 0, ECC Level L: 01)
        // Precomputed format bits for (ECC-L, Mask 0) = 0x77c4 with BCH
        const formatBits = [1, 1, 1, 0, 1, 1, 1, 1, 1, 0, 0, 0, 1, 0, 0];
        // Top-left
        let fIdx = 0;
        for (let c = 0; c <= 5; c++) matrix[8][c] = formatBits[fIdx++];
        matrix[8][7] = formatBits[fIdx++];
        matrix[8][8] = formatBits[fIdx++];
        matrix[7][8] = formatBits[fIdx++];
        for (let r = 5; r >= 0; r--) matrix[r][8] = formatBits[fIdx++];

        // Bottom-left & Top-right
        fIdx = 0;
        for (let r = matrixSize - 1; r >= matrixSize - 7; r--) matrix[r][8] = formatBits[fIdx++];
        matrix[8][matrixSize - 8] = formatBits[fIdx++];
        for (let c = matrixSize - 7; c < matrixSize; c++) matrix[8][c] = formatBits[fIdx++];

        // 8. Render clean SVG
        const dim = matrixSize + margin * 2;
        let paths = '';
        for (let r = 0; r < matrixSize; r++) {
            for (let c = 0; c < matrixSize; c++) {
                if (matrix[r][c] === 1) {
                    paths += `M${c + margin},${r + margin}h1v1h-1z `;
                }
            }
        }

        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${dim} ${dim}" width="${size}" height="${size}" shape-rendering="crispEdges">
            <rect width="${dim}" height="${dim}" fill="${fill}" rx="2"/>
            <path d="${paths.trim()}" fill="${color}"/>
        </svg>`;
    }

    return {
        createSVG: createQRCodeSVG,
    };
});
