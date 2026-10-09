import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="Fruit Ninja",
    page_icon="🍉",
    layout="wide"
)

game = """
<!DOCTYPE html>
<html>
<head>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: #080d1c;
    color: white;
    font-family: Arial, sans-serif;
}

#game {
    position: relative;
    width: 100%;
    height: 700px;
    overflow: hidden;

    border-radius: 25px;
    border: 4px solid #6366f1;

    background:
        radial-gradient(
            circle at 50% 30%,
            #312e81,
            #111827 55%,
            #020617
        );

    cursor: crosshair;
}

/* =========================
   TITLE
========================= */

#title {
    position: absolute;
    top: 20px;
    width: 100%;

    text-align: center;

    font-size: 48px;
    font-weight: 900;

    text-shadow:
        0 0 10px #818cf8,
        0 0 25px #6366f1;

    z-index: 10;
}

/* =========================
   SCORE
========================= */

#score {
    position: absolute;

    top: 90px;
    left: 30px;

    padding: 10px 20px;

    background: rgba(0,0,0,0.5);

    border-radius: 15px;

    font-size: 24px;
    font-weight: bold;

    z-index: 10;
}

/* =========================
   LIVES - 3 ONLY
========================= */

#lives {
    position: absolute;

    top: 90px;
    right: 30px;

    font-size: 30px;

    z-index: 10;

    max-width: 350px;
}

/* =========================
   MESSAGE
========================= */

#message {
    position: absolute;

    top: 140px;

    width: 100%;

    text-align: center;

    color: #c7d2fe;

    font-size: 18px;

    z-index: 10;
}

/* =========================
   START / RESTART BUTTON
========================= */

#start {
    position: absolute;

    top: 50%;
    left: 50%;

    transform: translate(-50%, -50%);

    padding: 18px 45px;

    border: none;

    border-radius: 15px;

    background:
        linear-gradient(
            135deg,
            #4f46e5,
            #7c3aed
        );

    color: white;

    font-size: 24px;

    font-weight: bold;

    cursor: pointer;

    box-shadow:
        0 10px 30px
        rgba(99,102,241,0.5);

    z-index: 50;

    transition: 0.2s;
}

#start:hover {

    transform:
        translate(-50%, -50%)
        scale(1.05);

    box-shadow:
        0 15px 40px
        rgba(124,58,237,0.7);
}

/* =========================
   FRUIT
========================= */

.fruit {
    position: absolute;

    font-size: 65px;

    user-select: none;

    pointer-events: none;

    filter:
        drop-shadow(
            0 8px 10px
            rgba(0,0,0,0.5)
        );

    z-index: 5;

    transform-origin: center;
}

/* =========================
   SLICE EFFECT
========================= */

.slice {
    position: absolute;

    height: 6px;

    background: white;

    border-radius: 50%;

    box-shadow:
        0 0 10px white,
        0 0 20px #c7d2fe;

    pointer-events: none;

    animation:
        slashAnimation
        0.25s
        ease-out
        forwards;

    z-index: 30;
}

@keyframes slashAnimation {

    0% {
        opacity: 1;

        transform:
            rotate(-35deg)
            scaleX(0.3);
    }

    100% {
        opacity: 0;

        transform:
            rotate(-35deg)
            scaleX(1.5);
    }

}

/* =========================
   JUICE SPLASH
========================= */

.juice {
    position: absolute;

    width: 10px;
    height: 10px;

    border-radius: 50%;

    pointer-events: none;

    z-index: 25;

    animation:
        juiceSplash
        0.8s
        ease-out
        forwards;
}

@keyframes juiceSplash {

    0% {
        opacity: 1;

        transform:
            translate(0, 0)
            scale(1.2);
    }

    50% {
        opacity: 1;
    }

    100% {
        opacity: 0;

        transform:
            translate(var(--dx), var(--dy))
            scale(0.35);
    }

}

/* =========================
   BIG JUICE SPLASH
========================= */

.juice-big {
    position: absolute;

    width: 25px;
    height: 25px;

    border-radius: 50%;

    pointer-events: none;

    z-index: 24;

    opacity: 0.9;

    animation:
        juiceBigSplash
        0.5s
        ease-out
        forwards;
}

@keyframes juiceBigSplash {

    0% {
        transform:
            scale(0.2);

        opacity: 0;
    }

    30% {
        transform:
            scale(1.2);

        opacity: 0.9;
    }

    100% {
        transform:
            scale(2.5);

        opacity: 0;
    }

}

/* =========================
   JUICE DROP
========================= */

.juice-drop {
    position: absolute;

    width: 7px;
    height: 14px;

    border-radius:
        50% 50% 55% 55%;

    pointer-events: none;

    z-index: 26;

    animation:
        juiceDrop
        1s
        ease-in
        forwards;
}

@keyframes juiceDrop {

    0% {
        opacity: 1;

        transform:
            translate(0, 0)
            rotate(0deg)
            scale(1);
    }

    100% {
        opacity: 0;

        transform:
            translate(var(--drop-x), var(--drop-y))
            rotate(25deg)
            scale(0.5);
    }

}

/* =========================
   GAME OVER
========================= */

#gameover {
    display: none;

    position: absolute;

    top: 50%;
    left: 50%;

    transform:
        translate(-50%, -50%);

    width: 100%;

    text-align: center;

    z-index: 40;

    pointer-events: none;
}

#gameover h1 {

    font-size: 55px;

    color: #fb7185;

    text-shadow:
        0 0 20px #f43f5e;

    margin-bottom: 10px;
}

#finalScore {

    font-size: 28px;

    color: white;
}

/* =========================
   DARK GAME OVER EFFECT
========================= */

#gameOverBackground {

    display: none;

    position: absolute;

    top: 0;
    left: 0;

    width: 100%;
    height: 100%;

    background:
        rgba(0,0,0,0.65);

    z-index: 35;
}

</style>

</head>

<body>

<div id="game">

    <!-- TITLE -->

    <div id="title">
        🍉 FRUIT NINJA 🍓
    </div>

    <!-- SCORE -->

    <div id="score">
        Score: 0
    </div>

    <!-- 3 LIVES -->

    <div id="lives">
        ❤️❤️❤️
    </div>

    <!-- MESSAGE -->

    <div id="message">
        Press START GAME to begin
    </div>

    <!-- START / RESTART BUTTON -->

    <button id="start">
        ▶ START GAME
    </button>

    <!-- GAME OVER DARK BACKGROUND -->

    <div id="gameOverBackground"></div>

    <!-- GAME OVER -->

    <div id="gameover">

        <h1>
            💀 GAME OVER
        </h1>

        <div id="finalScore">
            Final Score: 0
        </div>

    </div>

</div>

<script>

/* =========================
   GAME ELEMENTS
========================= */

const game =
    document.getElementById("game");

const scoreText =
    document.getElementById("score");

const livesText =
    document.getElementById("lives");

const message =
    document.getElementById("message");

const startButton =
    document.getElementById("start");

const gameOverScreen =
    document.getElementById("gameover");

const gameOverBackground =
    document.getElementById(
        "gameOverBackground"
    );

const finalScore =
    document.getElementById(
        "finalScore"
    );

/* =========================
   GAME VARIABLES
========================= */

let score = 0;

/* Only 3 lives */

let lives = 3;

let running = false;

let fruits = [];

let fruitTimer = null;

let animation = null;

let lastSliceTime = 0;

/* =========================
   FRUIT TYPES
========================= */

const fruitTypes = [

    "🍎",
    "🍊",
    "🍉",
    "🍓",
    "🍍",
    "🥝",
    "🍌",
    "🥭"

];

/* =========================
   FRUIT JUICE COLORS
========================= */

const fruitJuiceColors = {

    "🍎": "#ff3b30",
    "🍊": "#ff9500",
    "🍉": "#ff375f",
    "🍓": "#ff2d55",
    "🍍": "#ffd60a",
    "🥝": "#30d158",
    "🍌": "#ffd60a",
    "🥭": "#ff9f0a"

};

/* =========================
   START / RESTART GAME
========================= */

startButton.addEventListener(
    "click",
    startGame
);

function startGame() {

    /* Stop any old game */

    clearInterval(fruitTimer);

    cancelAnimationFrame(animation);

    /* Remove old fruits */

    fruits.forEach(function(fruit) {

        if (fruit.element) {

            fruit.element.remove();

        }

    });

    fruits = [];

    /* Remove old juice effects */

    document
        .querySelectorAll(".juice")
        .forEach(function(effect) {

            effect.remove();

        });

    document
        .querySelectorAll(".juice-big")
        .forEach(function(effect) {

            effect.remove();

        });

    document
        .querySelectorAll(".juice-drop")
        .forEach(function(effect) {

            effect.remove();

        });

    /* Reset score */

    score = 0;

    /* Reset lives to 3 */

    lives = 3;

    /* Reset game */

    running = true;

    /* Reset display */

    scoreText.innerText =
        "Score: 0";

    updateLives();

    message.innerText =
        "🗡️ Click or drag across the fruits!";

    /* Hide game over */

    gameOverScreen.style.display =
        "none";

    gameOverBackground.style.display =
        "none";

    /* Change button */

    startButton.innerText =
        "🔄 RESTART GAME";

    startButton.style.display =
        "none";

    /* Start creating fruits */

    fruitTimer =
        setInterval(
            createFruit,
            900
        );

    /* Start animation */

    animation =
        requestAnimationFrame(
            update
        );

}

/* =========================
   CREATE FRUIT
========================= */

function createFruit() {

    if (!running) {

        return;

    }

    const fruit =
        document.createElement(
            "div"
        );

    fruit.className =
        "fruit";

    /* Select random fruit */

    const fruitType =
        fruitTypes[
            Math.floor(
                Math.random() *
                fruitTypes.length
            )
        ];

    fruit.innerText =
        fruitType;

    /* Random horizontal position */

    const x =
        Math.random() *
        (game.clientWidth - 80);

    /* Start below the game */

    const y =
        game.clientHeight + 30;

    fruit.style.left =
        x + "px";

    fruit.style.top =
        y + "px";

    game.appendChild(
        fruit
    );

    fruits.push({

        element: fruit,

        type: fruitType,

        x: x,

        y: y,

        /* Slow horizontal movement */

        vx:
            (Math.random() - 0.5)
            * 1.5,

        /* Slow upward movement */

        vy:
            -(Math.random() * 4 + 7),

        /* Gravity */

        gravity:
            0.16,

        sliced: false

    });

}

/* =========================
   UPDATE GAME
========================= */

function update() {

    if (!running) {

        return;

    }

    for (
        let i = fruits.length - 1;
        i >= 0;
        i--
    ) {

        const fruit =
            fruits[i];

        /* Move fruit */

        fruit.x +=
            fruit.vx;

        fruit.y +=
            fruit.vy;

        /* Gravity */

        fruit.vy +=
            fruit.gravity;

        /* Update position */

        fruit.element.style.left =
            fruit.x + "px";

        fruit.element.style.top =
            fruit.y + "px";

        /* Fruit missed */

        if (
            fruit.y >
            game.clientHeight + 100
        ) {

            fruit.element.remove();

            fruits.splice(
                i,
                1
            );

            /* Lose one life */

            lives--;

            updateLives();

            /* Game over after 3 misses */

            if (
                lives <= 0
            ) {

                endGame();

                return;

            }

        }

    }

    animation =
        requestAnimationFrame(
            update
        );

}

/* =========================
   CLICK TO SLICE
========================= */

game.addEventListener(
    "pointerdown",
    function(event) {

        sliceAt(
            event.clientX,
            event.clientY
        );

    }
);

/* =========================
   DRAG TO SLICE
========================= */

game.addEventListener(
    "pointermove",
    function(event) {

        if (
            event.buttons === 1
        ) {

            sliceAt(
                event.clientX,
                event.clientY
            );

        }

    }
);

/* =========================
   SLICE FUNCTION
========================= */

function sliceAt(
    clientX,
    clientY
) {

    if (!running) {

        return;

    }

    /* Prevent excessive slicing */

    const now =
        Date.now();

    if (
        now - lastSliceTime < 50
    ) {

        return;

    }

    lastSliceTime =
        now;

    /* Get game position */

    const rect =
        game.getBoundingClientRect();

    const mouseX =
        clientX -
        rect.left;

    const mouseY =
        clientY -
        rect.top;

    /* Check every fruit */

    for (
        let i = fruits.length - 1;
        i >= 0;
        i--
    ) {

        const fruit =
            fruits[i];

        /* Fruit center */

        const centerX =
            fruit.x + 32;

        const centerY =
            fruit.y + 32;

        /* Distance from cursor */

        const distance =
            Math.sqrt(

                Math.pow(
                    mouseX -
                    centerX,
                    2
                )

                +

                Math.pow(
                    mouseY -
                    centerY,
                    2
                )

            );

        /* Larger hit area */

        if (
            distance < 65 &&
            !fruit.sliced
        ) {

            fruit.sliced =
                true;

            /* Increase score */

            score++;

            scoreText.innerText =
                "Score: " +
                score;

            /* Create sword slash */

            createSlash(
                mouseX,
                mouseY
            );

            /* Create juice */

            createJuiceSplash(
                centerX,
                centerY,
                fruit.type
            );

            /* Remove fruit */

            fruit.element.remove();

            fruits.splice(
                i,
                1
            );

        }

    }

}

/* =========================
   SLASH EFFECT
========================= */

function createSlash(
    x,
    y
) {

    const slash =
        document.createElement(
            "div"
        );

    slash.className =
        "slice";

    slash.style.left =
        (x - 50) + "px";

    slash.style.top =
        y + "px";

    slash.style.width =
        "100px";

    game.appendChild(
        slash
    );

    setTimeout(
        function() {

            slash.remove();

        },
        250
    );

}

/* =========================
   JUICE SQUEEZE EFFECT
========================= */

function createJuiceSplash(
    x,
    y,
    fruitType
) {

    /* Get juice color */

    const juiceColor =
        fruitJuiceColors[fruitType]
        || "#ff3b30";

    /* =========================
       BIG JUICE SPLASH
    ========================= */

    const bigSplash =
        document.createElement(
            "div"
        );

    bigSplash.className =
        "juice-big";

    bigSplash.style.left =
        (x - 12) + "px";

    bigSplash.style.top =
        (y - 12) + "px";

    bigSplash.style.background =
        juiceColor;

    game.appendChild(
        bigSplash
    );

    setTimeout(
        function() {

            bigSplash.remove();

        },
        500
    );

    /* =========================
       FLYING JUICE DROPS
    ========================= */

    for (
        let i = 0;
        i < 14;
        i++
    ) {

        const drop =
            document.createElement(
                "div"
            );

        drop.className =
            "juice";

        drop.style.left =
            (x - 6) + "px";

        drop.style.top =
            (y - 6) + "px";

        /* Random spray */

        const dx =
            (Math.random() - 0.5)
            * 180;

        const dy =
            (Math.random() - 0.8)
            * 150;

        drop.style.setProperty(
            "--dx",
            dx + "px"
        );

        drop.style.setProperty(
            "--dy",
            dy + "px"
        );

        /* Random size */

        const size =
            Math.random() * 10 + 6;

        drop.style.width =
            size + "px";

        drop.style.height =
            size + "px";

        /* Fruit-specific juice */

        drop.style.background =
            juiceColor;

        game.appendChild(
            drop
        );

        setTimeout(
            function() {

                drop.remove();

            },
            800
        );

    }

    /* =========================
       DRIPPING JUICE
    ========================= */

    for (
        let i = 0;
        i < 5;
        i++
    ) {

        const drip =
            document.createElement(
                "div"
            );

        drip.className =
            "juice-drop";

        drip.style.left =
            (
                x +
                (Math.random() - 0.5)
                * 35
            ) + "px";

        drip.style.top =
            (
                y +
                Math.random() * 15
            ) + "px";

        /* Falling direction */

        const dropX =
            (Math.random() - 0.5)
            * 70;

        const dropY =
            Math.random() * 100 + 50;

        drip.style.setProperty(
            "--drop-x",
            dropX + "px"
        );

        drip.style.setProperty(
            "--drop-y",
            dropY + "px"
        );

        drip.style.background =
            juiceColor;

        game.appendChild(
            drip
        );

        setTimeout(
            function() {

                drip.remove();

            },
            1000
        );

    }

}

/* =========================
   UPDATE LIVES
========================= */

function updateLives() {

    let hearts = "";

    /* Only 3 hearts */

    for (
        let i = 0;
        i < 3;
        i++
    ) {

        if (
            i < lives
        ) {

            hearts +=
                "❤️";

        }

        else {

            hearts +=
                "🖤";

        }

    }

    livesText.innerText =
        hearts;

}

/* =========================
   GAME OVER
========================= */

function endGame() {

    running = false;

    /* Stop spawning fruits */

    clearInterval(
        fruitTimer
    );

    /* Stop animation */

    cancelAnimationFrame(
        animation
    );

    /* Show game over */

    gameOverBackground.style.display =
        "block";

    gameOverScreen.style.display =
        "block";

    /* Show final score */

    finalScore.innerText =
        "Final Score: " +
        score;

    /* Change button */

    startButton.innerText =
        "🔄 PLAY AGAIN";

    startButton.style.display =
        "block";

    /* Keep button above game-over */

    startButton.style.zIndex =
        "100";

}

/* =========================
   INITIAL SCREEN
========================= */

updateLives();

</script>

</body>
</html>
"""

components.html(
    game,
    height=850
)