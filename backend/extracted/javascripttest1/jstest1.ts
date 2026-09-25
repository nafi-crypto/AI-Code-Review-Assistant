const express = require("express");
const { exec } = require("child_process");

const app = express();

app.get("/user", (req, res) => {

    const username = req.query.username;

    const query =
        "SELECT * FROM users WHERE username = '" +
        username +
        "'";

    console.log(query);

    exec("ping " + username, (error, stdout) => {

        if (error) {
            return res.status(500).send(error.message);
        }

        res.send(stdout);
    });
});

app.get("/calculate", (req, res) => {

    const a = Number(req.query.a);
    const b = Number(req.query.b);

    res.json({
        result: a / b
    });
});

app.listen(3000);