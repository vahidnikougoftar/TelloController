import pygame

def init():
    pygame.init()
    screen = pygame.display.set_mode((400, 400))
    pygame.display.set_caption("Key Press Module")

# get key press events
def get_key_events(keyName):
    ans = False
    keyInput = pygame.key.get_pressed()
    myKey = getattr(pygame, f'K_{keyName}')
    if keyInput[myKey]:
        ans = True
    pygame.display.update()
    return ans

    
if __name__ == "__main__":
    init()
