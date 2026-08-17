/*
 * Presentation shim for the Coil Snake example.
 *
 * This file owns the SDL window, the keyboard, the clock, and the pixels — and
 * nothing else. It has no board, no snake, no food, no score and no notion of
 * wrapping or collisions: every rule of the game lives in the Coil engine
 * (src/engine.coil), which drives these functions from src/main.coil.
 */

#include <SDL2/SDL.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>

/* Input codes handed back to the Coil engine loop. Keep in sync with the
 * INPUT-* constants in src/main.coil. */
#define INPUT_NONE 0
#define INPUT_QUIT 1
#define INPUT_UP 2
#define INPUT_DOWN 3
#define INPUT_LEFT 4
#define INPUT_RIGHT 5
#define INPUT_RESTART 6

/* Cell kinds handed in by the Coil engine loop. */
#define KIND_FOOD 0
#define KIND_HEAD 1
#define KIND_BODY 2

#define PANEL_H 34

static SDL_Window *window;
static SDL_Renderer *renderer;
static int cell_px = 24;
static int cols_cached = 30;
static int rows_cached = 22;

/* Opens the window. Returns 0 on success, nonzero when there is no usable
 * display (a headless machine, for instance). */
int64_t snake_window_open(int64_t cols, int64_t rows, int64_t cell) {
    cols_cached = (int)cols;
    rows_cached = (int)rows;
    cell_px = (int)cell;
    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_TIMER) != 0) return 1;
    window = SDL_CreateWindow("Coil Snake", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                              cols_cached * cell_px, rows_cached * cell_px + PANEL_H,
                              SDL_WINDOW_SHOWN);
    if (!window) { SDL_Quit(); return 2; }
    renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!renderer) renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE);
    if (!renderer) { SDL_DestroyWindow(window); window = NULL; SDL_Quit(); return 3; }
    return 0;
}

void snake_window_close(void) {
    if (renderer) { SDL_DestroyRenderer(renderer); renderer = NULL; }
    if (window) { SDL_DestroyWindow(window); window = NULL; }
    SDL_Quit();
}

/* One pending keyboard/window event, translated into an engine-neutral code.
 * INPUT_NONE means the queue is empty. */
int64_t snake_window_poll(void) {
    SDL_Event e;
    while (SDL_PollEvent(&e)) {
        if (e.type == SDL_QUIT) return INPUT_QUIT;
        if (e.type == SDL_KEYDOWN) {
            switch (e.key.keysym.sym) {
                case SDLK_ESCAPE: return INPUT_QUIT;
                case SDLK_UP: case SDLK_w: return INPUT_UP;
                case SDLK_DOWN: case SDLK_s: return INPUT_DOWN;
                case SDLK_LEFT: case SDLK_a: return INPUT_LEFT;
                case SDLK_RIGHT: case SDLK_d: return INPUT_RIGHT;
                case SDLK_SPACE: case SDLK_RETURN: return INPUT_RESTART;
                default: break;
            }
        }
    }
    return INPUT_NONE;
}

/* Milliseconds since the window opened. */
int64_t snake_window_ticks(void) { return (int64_t)SDL_GetTicks(); }

void snake_window_delay(int64_t ms) { SDL_Delay((Uint32)(ms < 0 ? 0 : ms)); }

/* A seed for the engine's deterministic random number generator. */
int64_t snake_window_seed(void) { return (int64_t)time(NULL); }

void snake_window_begin_frame(void) {
    if (!renderer) return;
    SDL_SetRenderDrawColor(renderer, 12, 17, 25, 255);
    SDL_RenderClear(renderer);
    SDL_Rect board = {0, 0, cols_cached * cell_px, rows_cached * cell_px};
    SDL_SetRenderDrawColor(renderer, 20, 29, 40, 255);
    SDL_RenderFillRect(renderer, &board);
}

void snake_window_draw_cell(int64_t x, int64_t y, int64_t kind) {
    if (!renderer) return;
    if (kind == KIND_FOOD) SDL_SetRenderDrawColor(renderer, 240, 80, 85, 255);
    else if (kind == KIND_HEAD) SDL_SetRenderDrawColor(renderer, 112, 220, 140, 255);
    else SDL_SetRenderDrawColor(renderer, 67, 180, 105, 255);
    int inset = kind == KIND_FOOD ? 3 : 2;
    SDL_Rect r = {(int)x * cell_px + inset, (int)y * cell_px + inset,
                  cell_px - 2 * inset, cell_px - 2 * inset};
    SDL_RenderFillRect(renderer, &r);
}

/* The status line lives in the window title so the example needs no font
 * dependency. `over` is the engine's game-over flag. */
void snake_window_set_status(int64_t score, int64_t over) {
    if (!window) return;
    char title[160];
    if (over)
        snprintf(title, sizeof(title),
                 "Coil Snake — Score: %lld — GAME OVER (Space/Enter restarts, Esc quits)",
                 (long long)score);
    else
        snprintf(title, sizeof(title),
                 "Coil Snake — Score: %lld — WASD/arrows, edges wrap, Esc quits",
                 (long long)score);
    SDL_SetWindowTitle(window, title);
}

void snake_window_end_frame(void) {
    if (!renderer) return;
    SDL_Rect panel = {0, rows_cached * cell_px, cols_cached * cell_px, PANEL_H};
    SDL_SetRenderDrawColor(renderer, 10, 14, 20, 255);
    SDL_RenderFillRect(renderer, &panel);
    SDL_RenderPresent(renderer);
}
